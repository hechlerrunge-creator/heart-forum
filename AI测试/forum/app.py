import os
import io
import random
import string
from datetime import datetime
from functools import wraps

from flask import (Flask, render_template, redirect, url_for, flash,
                   request, abort, session, jsonify, Response)
from flask_login import (LoginManager, login_user, logout_user,
                         login_required, current_user)
from flask_wtf.csrf import generate_csrf
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from models import db, User, Category, Post, Reply, Hug, HugReply, Message, BannedWord, Report, ContentReview
from forms import (RegisterForm, LoginForm, PostForm, ReplyForm, ProfileForm,
                   CategoryForm, ChangePasswordForm, MessageForm, BannedWordForm, ReportForm)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'heart-forum-secret-key-2026'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///forum.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = '请先登录'
login_manager.login_message_category = 'warning'


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ===================== 验证码工具 =====================
def generate_captcha_text(length=4):
    chars = string.ascii_uppercase + string.digits
    # 去掉容易混淆的字符
    chars = chars.replace('O', '').replace('0', '').replace('I', '').replace('1', '')
    return ''.join(random.choices(chars, k=length))


def generate_captcha_image(text):
    width, height = 120, 40
    # 背景色
    bg_color = (random.randint(230, 255), random.randint(230, 255), random.randint(230, 255))
    img = Image.new('RGB', (width, height), bg_color)
    draw = ImageDraw.Draw(img)

    # 画干扰线
    for _ in range(5):
        x1 = random.randint(0, width)
        y1 = random.randint(0, height)
        x2 = random.randint(0, width)
        y2 = random.randint(0, height)
        draw.line([(x1, y1), (x2, y2)], fill=(
            random.randint(100, 200), random.randint(100, 200), random.randint(100, 200)), width=1)

    # 画干扰点
    for _ in range(30):
        x = random.randint(0, width)
        y = random.randint(0, height)
        draw.point((x, y), fill=(random.randint(0, 200), random.randint(0, 200), random.randint(0, 200)))

    # 绘制文字
    font_size = 26
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except Exception:
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()

    char_width = width // (len(text) + 1)
    for i, char in enumerate(text):
        x = char_width * i + random.randint(5, 10)
        y = random.randint(3, 10)
        color = (random.randint(20, 100), random.randint(20, 100), random.randint(20, 100))
        draw.text((x, y), char, font=font, fill=color)

    # 轻微模糊
    img = img.filter(ImageFilter.SMOOTH)

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf


@app.route('/captcha')
def captcha():
    text = generate_captcha_text()
    session['captcha'] = text.upper()
    buf = generate_captcha_image(text)
    return Response(buf.read(), mimetype='image/png')


def verify_captcha(input_text):
    expected = session.pop('captcha', '')
    return input_text.upper() == expected.upper()


# ===================== 内容过滤 =====================
def filter_content(text):
    """检查内容是否含违禁词，返回 (is_ok, filtered_text)"""
    words = BannedWord.query.all()
    original = text
    for bw in words:
        if bw.word.lower() in text.lower():
            # 替换为星号
            text = text.lower().replace(bw.word.lower(), '*' * len(bw.word))
    # 重新按原始大小写替换（简单方案：直接屏蔽整个词）
    result = original
    found = False
    for bw in words:
        import re
        pattern = re.compile(re.escape(bw.word), re.IGNORECASE)
        if pattern.search(result):
            found = True
            result = pattern.sub('**' * len(bw.word), result)
    return not found, result


# ===================== 上下文处理器 =====================
@app.context_processor
def inject_globals():
    categories = Category.query.all()
    unread_count = 0
    if current_user.is_authenticated:
        unread_count = current_user.unread_message_count()
    # 管理员侧边栏徽章数据
    report_count = 0
    review_pending_count = 0
    if current_user.is_authenticated and current_user.is_admin:
        report_count = Report.query.filter_by(is_handled=False).count()
        review_pending_count = ContentReview.query.filter_by(status='pending').count()
    return dict(categories=categories, now=datetime.utcnow(), unread_count=unread_count,
                report_count=report_count, review_pending_count=review_pending_count,
                csrf_token=generate_csrf)


# ===================== 首页 =====================
@app.route('/')
def index():
    page = request.args.get('page', 1, type=int)
    category_id = request.args.get('category', 0, type=int)
    q = request.args.get('q', '').strip()

    query = Post.query
    if category_id:
        query = query.filter_by(category_id=category_id)
    if q:
        query = query.filter(Post.title.contains(q))

    pinned_posts = []
    if not category_id and not q:
        pinned_posts = Post.query.filter_by(is_pinned=True).order_by(Post.created_at.desc()).all()

    posts = query.order_by(Post.is_pinned.desc(), Post.created_at.desc()).paginate(
        page=page, per_page=15, error_out=False
    )
    return render_template('index.html', posts=posts, pinned_posts=pinned_posts,
                           category_id=category_id, q=q)


# ===================== 帖子详情 =====================
@app.route('/post/<int:post_id>', methods=['GET', 'POST'])
def post_detail(post_id):
    post = Post.query.get_or_404(post_id)
    post.views += 1
    db.session.commit()

    form = ReplyForm()
    report_form = ReportForm()
    page = request.args.get('page', 1, type=int)
    replies = post.replies.order_by(Reply.created_at.asc()).paginate(
        page=page, per_page=20, error_out=False
    )

    # 当前用户是否已拥抱
    user_hugged = False
    if current_user.is_authenticated:
        user_hugged = Hug.query.filter_by(user_id=current_user.id, post_id=post.id).first() is not None

    # 当前用户已拥抱的回复id集合
    hugged_reply_ids = set()
    if current_user.is_authenticated:
        for hr in HugReply.query.filter_by(user_id=current_user.id).all():
            hugged_reply_ids.add(hr.reply_id)

    if form.validate_on_submit():
        if not current_user.is_authenticated:
            flash('请先登录后再回复', 'warning')
            return redirect(url_for('login'))
        if post.is_locked and not current_user.is_admin:
            flash('该帖子已锁定，无法回复', 'warning')
            return redirect(url_for('post_detail', post_id=post_id))
        if current_user.is_banned:
            flash('您的账号已被封禁', 'danger')
            return redirect(url_for('post_detail', post_id=post_id))

        content = form.content.data
        is_ok, filtered = filter_content(content)
        if not is_ok:
            flash('您的回复包含违禁内容，已被拦截。请文明发言！', 'danger')
            return redirect(url_for('post_detail', post_id=post_id))

        reply = Reply(
            content=content,
            user_id=current_user.id,
            post_id=post.id,
            is_anonymous=form.is_anonymous.data
        )
        db.session.add(reply)
        db.session.commit()
        flash('回复成功！', 'success')
        return redirect(url_for('post_detail', post_id=post_id))

    return render_template('post_detail.html', post=post, form=form,
                           report_form=report_form, replies=replies,
                           user_hugged=user_hugged,
                           hugged_reply_ids=hugged_reply_ids)


# ===================== 拥抱 API =====================
@app.route('/api/hug/post/<int:post_id>', methods=['POST'])
@login_required
def hug_post(post_id):
    post = Post.query.get_or_404(post_id)
    existing = Hug.query.filter_by(user_id=current_user.id, post_id=post_id).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        return jsonify({'hugged': False, 'count': post.hug_count})
    else:
        hug = Hug(user_id=current_user.id, post_id=post_id)
        db.session.add(hug)
        db.session.commit()
        return jsonify({'hugged': True, 'count': post.hug_count})


@app.route('/api/hug/reply/<int:reply_id>', methods=['POST'])
@login_required
def hug_reply(reply_id):
    reply = Reply.query.get_or_404(reply_id)
    existing = HugReply.query.filter_by(user_id=current_user.id, reply_id=reply_id).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        return jsonify({'hugged': False, 'count': reply.hug_count})
    else:
        hug = HugReply(user_id=current_user.id, reply_id=reply_id)
        db.session.add(hug)
        db.session.commit()
        return jsonify({'hugged': True, 'count': reply.hug_count})


# ===================== 举报 =====================
@app.route('/report/post/<int:post_id>', methods=['POST'])
@login_required
def report_post(post_id):
    post = Post.query.get_or_404(post_id)
    form = ReportForm()
    if form.validate_on_submit():
        # 检查是否重复举报
        existing = Report.query.filter_by(reporter_id=current_user.id, post_id=post_id).first()
        if existing:
            flash('您已经举报过该帖子', 'info')
        else:
            report = Report(reporter_id=current_user.id, post_id=post_id, reason=form.reason.data)
            db.session.add(report)
            db.session.commit()
            flash('举报已提交，感谢您的反馈', 'success')
    return redirect(url_for('post_detail', post_id=post_id))


@app.route('/report/reply/<int:reply_id>', methods=['POST'])
@login_required
def report_reply(reply_id):
    reply = Reply.query.get_or_404(reply_id)
    reason = request.form.get('reason', '其他')
    existing = Report.query.filter_by(reporter_id=current_user.id, reply_id=reply_id).first()
    if existing:
        flash('您已经举报过该评论', 'info')
    else:
        report = Report(reporter_id=current_user.id, reply_id=reply_id, reason=reason)
        db.session.add(report)
        db.session.commit()
        flash('举报已提交', 'success')
    return redirect(url_for('post_detail', post_id=reply.post_id))


# ===================== 用户注册 / 登录 / 登出 =====================
@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = RegisterForm()
    if form.validate_on_submit():
        # 验证验证码
        if not verify_captcha(form.captcha.data):
            flash('验证码错误', 'danger')
            return render_template('register.html', form=form)
        user = User(username=form.username.data)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash('注册成功，请登录！', 'success')
        return redirect(url_for('login'))
    return render_template('register.html', form=form)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = LoginForm()
    if form.validate_on_submit():
        # 验证验证码
        if not verify_captcha(form.captcha.data):
            flash('验证码错误', 'danger')
            return render_template('login.html', form=form)
        user = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data):
            if user.is_banned:
                flash('您的账号已被封禁，请联系管理员', 'danger')
                return redirect(url_for('login'))
            login_user(user, remember=form.remember.data)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('index'))
        flash('用户名或密码错误', 'danger')
    return render_template('login.html', form=form)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('已退出登录', 'info')
    return redirect(url_for('index'))


# ===================== 用户中心 =====================
@app.route('/user/<int:user_id>')
def user_profile(user_id):
    user = User.query.get_or_404(user_id)
    # 只展示非匿名帖子（对外展示）
    posts = Post.query.filter_by(user_id=user_id, is_anonymous=False).order_by(Post.created_at.desc()).limit(10).all()
    replies = Reply.query.filter_by(user_id=user_id, is_anonymous=False).order_by(Reply.created_at.desc()).limit(10).all()
    return render_template('user/profile.html', profile_user=user, posts=posts, replies=replies)


@app.route('/user/settings', methods=['GET', 'POST'])
@login_required
def user_settings():
    profile_form = ProfileForm(obj=current_user)
    pwd_form = ChangePasswordForm()

    if 'save_profile' in request.form and profile_form.validate_on_submit():
        current_user.bio = profile_form.bio.data
        db.session.commit()
        flash('个人资料已更新', 'success')
        return redirect(url_for('user_settings'))

    if 'change_password' in request.form and pwd_form.validate_on_submit():
        if not current_user.check_password(pwd_form.old_password.data):
            flash('当前密码不正确', 'danger')
        else:
            current_user.set_password(pwd_form.new_password.data)
            db.session.commit()
            flash('密码修改成功', 'success')
        return redirect(url_for('user_settings'))

    return render_template('user/settings.html', profile_form=profile_form, pwd_form=pwd_form)


@app.route('/user/posts')
@login_required
def user_posts():
    page = request.args.get('page', 1, type=int)
    posts = Post.query.filter_by(user_id=current_user.id).order_by(Post.created_at.desc()).paginate(
        page=page, per_page=10, error_out=False
    )
    return render_template('user/my_posts.html', posts=posts)


# ===================== 私信 =====================
@app.route('/messages')
@login_required
def messages():
    """私信收件箱 - 按对话分组"""
    # 找出所有与当前用户有过对话的用户
    from sqlalchemy import or_, and_
    conversations = db.session.query(Message).filter(
        or_(
            and_(Message.sender_id == current_user.id, Message.is_deleted_by_sender == False),
            and_(Message.receiver_id == current_user.id, Message.is_deleted_by_receiver == False)
        )
    ).order_by(Message.created_at.desc()).all()

    # 构建对话列表（去重，每个用户只保留最新一条）
    seen_users = {}
    for msg in conversations:
        other_id = msg.receiver_id if msg.sender_id == current_user.id else msg.sender_id
        if other_id not in seen_users:
            other_user = User.query.get(other_id)
            unread = Message.query.filter_by(
                sender_id=other_id, receiver_id=current_user.id, is_read=False, is_deleted_by_receiver=False
            ).count()
            seen_users[other_id] = {
                'user': other_user,
                'last_msg': msg,
                'unread': unread
            }

    convs = sorted(seen_users.values(), key=lambda x: x['last_msg'].created_at, reverse=True)
    return render_template('user/messages.html', conversations=convs)


@app.route('/messages/<int:user_id>', methods=['GET', 'POST'])
@login_required
def message_thread(user_id):
    """与某用户的对话详情"""
    other = User.query.get_or_404(user_id)
    if other.id == current_user.id:
        flash('不能给自己发私信', 'warning')
        return redirect(url_for('messages'))

    form = MessageForm()
    if form.validate_on_submit():
        content = form.content.data
        is_ok, _ = filter_content(content)
        if not is_ok:
            flash('私信内容包含违禁词，请文明用语', 'danger')
            return redirect(url_for('message_thread', user_id=user_id))
        msg = Message(sender_id=current_user.id, receiver_id=user_id, content=content)
        db.session.add(msg)
        db.session.commit()
        flash('私信已发送', 'success')
        return redirect(url_for('message_thread', user_id=user_id))

    from sqlalchemy import or_, and_
    msgs = Message.query.filter(
        or_(
            and_(Message.sender_id == current_user.id, Message.receiver_id == user_id,
                 Message.is_deleted_by_sender == False),
            and_(Message.sender_id == user_id, Message.receiver_id == current_user.id,
                 Message.is_deleted_by_receiver == False)
        )
    ).order_by(Message.created_at.asc()).all()

    # 标记为已读
    Message.query.filter_by(sender_id=user_id, receiver_id=current_user.id, is_read=False).update({'is_read': True})
    db.session.commit()

    return render_template('user/message_thread.html', other=other, msgs=msgs, form=form)


@app.route('/messages/<int:msg_id>/delete', methods=['POST'])
@login_required
def delete_message(msg_id):
    msg = Message.query.get_or_404(msg_id)
    if msg.sender_id == current_user.id:
        msg.is_deleted_by_sender = True
    elif msg.receiver_id == current_user.id:
        msg.is_deleted_by_receiver = True
    else:
        abort(403)
    db.session.commit()
    return jsonify({'ok': True})


@app.route('/messages/send_to/<int:user_id>', methods=['GET'])
@login_required
def send_message_to(user_id):
    """跳转到与某用户的对话页面"""
    return redirect(url_for('message_thread', user_id=user_id))


# ===================== 发帖 =====================
@app.route('/post/new', methods=['GET', 'POST'])
@login_required
def new_post():
    if current_user.is_banned:
        flash('您的账号已被封禁，无法发帖', 'danger')
        return redirect(url_for('index'))
    form = PostForm()
    form.category_id.choices = [(c.id, c.name) for c in Category.query.all()]
    if form.validate_on_submit():
        content = form.content.data
        title = form.title.data
        is_ok_c, _ = filter_content(content)
        is_ok_t, _ = filter_content(title)
        if not is_ok_c or not is_ok_t:
            flash('帖子内容包含违禁词，请文明发言！', 'danger')
            return render_template('user/new_post.html', form=form)
        post = Post(
            title=title,
            content=content,
            user_id=current_user.id,
            category_id=form.category_id.data,
            is_anonymous=form.is_anonymous.data
        )
        db.session.add(post)
        db.session.commit()
        flash('发帖成功！', 'success')
        return redirect(url_for('post_detail', post_id=post.id))
    return render_template('user/new_post.html', form=form)


@app.route('/post/<int:post_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    form = PostForm(obj=post)
    form.category_id.choices = [(c.id, c.name) for c in Category.query.all()]
    if form.validate_on_submit():
        content = form.content.data
        title = form.title.data
        is_ok_c, _ = filter_content(content)
        is_ok_t, _ = filter_content(title)
        if not is_ok_c or not is_ok_t:
            flash('内容包含违禁词，请文明发言！', 'danger')
            return render_template('user/new_post.html', form=form, edit=True, post=post)
        post.title = title
        post.content = content
        post.category_id = form.category_id.data
        post.is_anonymous = form.is_anonymous.data
        db.session.commit()
        flash('帖子已更新', 'success')
        return redirect(url_for('post_detail', post_id=post.id))
    return render_template('user/new_post.html', form=form, edit=True, post=post)


@app.route('/post/<int:post_id>/delete', methods=['POST'])
@login_required
def delete_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    db.session.delete(post)
    db.session.commit()
    flash('帖子已删除', 'info')
    return redirect(url_for('index'))


@app.route('/reply/<int:reply_id>/delete', methods=['POST'])
@login_required
def delete_reply(reply_id):
    reply = Reply.query.get_or_404(reply_id)
    post_id = reply.post_id
    if reply.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    db.session.delete(reply)
    db.session.commit()
    flash('回复已删除', 'info')
    return redirect(url_for('post_detail', post_id=post_id))


# ===================== 管理员装饰器 =====================
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated


# ===================== 管理员后台 =====================
@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    user_count = User.query.count()
    post_count = Post.query.count()
    reply_count = Reply.query.count()
    report_count = Report.query.filter_by(is_handled=False).count()
    banned_word_count = BannedWord.query.count()
    review_pending_count = ContentReview.query.filter_by(status='pending').count()
    recent_posts = Post.query.order_by(Post.created_at.desc()).limit(5).all()
    recent_users = User.query.order_by(User.created_at.desc()).limit(5).all()
    recent_reports = Report.query.filter_by(is_handled=False).order_by(Report.created_at.desc()).limit(5).all()
    return render_template('admin/dashboard.html',
                           user_count=user_count, post_count=post_count,
                           reply_count=reply_count, report_count=report_count,
                           banned_word_count=banned_word_count,
                           review_pending_count=review_pending_count,
                           recent_posts=recent_posts, recent_users=recent_users,
                           recent_reports=recent_reports)


@app.route('/admin/users')
@login_required
@admin_required
def admin_users():
    page = request.args.get('page', 1, type=int)
    q = request.args.get('q', '').strip()
    query = User.query
    if q:
        query = query.filter(User.username.contains(q))
    users = query.order_by(User.created_at.desc()).paginate(page=page, per_page=20, error_out=False)
    return render_template('admin/users.html', users=users, q=q)


@app.route('/admin/user/<int:user_id>/toggle-ban', methods=['POST'])
@login_required
@admin_required
def toggle_ban(user_id):
    user = User.query.get_or_404(user_id)
    if user.is_admin:
        flash('不能封禁管理员', 'warning')
    else:
        user.is_banned = not user.is_banned
        db.session.commit()
        flash(f'用户 {user.username} 已{"封禁" if user.is_banned else "解封"}', 'success')
    return redirect(url_for('admin_users'))


@app.route('/admin/user/<int:user_id>/toggle-admin', methods=['POST'])
@login_required
@admin_required
def toggle_admin(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('不能修改自己的管理员权限', 'warning')
    else:
        user.is_admin = not user.is_admin
        db.session.commit()
        flash(f'用户 {user.username} 权限已更新', 'success')
    return redirect(url_for('admin_users'))


@app.route('/admin/posts')
@login_required
@admin_required
def admin_posts():
    page = request.args.get('page', 1, type=int)
    q = request.args.get('q', '').strip()
    query = Post.query
    if q:
        query = query.filter(Post.title.contains(q))
    posts = query.order_by(Post.created_at.desc()).paginate(page=page, per_page=20, error_out=False)
    return render_template('admin/posts.html', posts=posts, q=q)


@app.route('/admin/post/<int:post_id>/toggle-pin', methods=['POST'])
@login_required
@admin_required
def toggle_pin(post_id):
    post = Post.query.get_or_404(post_id)
    post.is_pinned = not post.is_pinned
    db.session.commit()
    flash(f'帖子已{"置顶" if post.is_pinned else "取消置顶"}', 'success')
    return redirect(url_for('admin_posts'))


@app.route('/admin/post/<int:post_id>/toggle-lock', methods=['POST'])
@login_required
@admin_required
def toggle_lock(post_id):
    post = Post.query.get_or_404(post_id)
    post.is_locked = not post.is_locked
    db.session.commit()
    flash(f'帖子已{"锁定" if post.is_locked else "解锁"}', 'success')
    return redirect(url_for('admin_posts'))


@app.route('/admin/post/<int:post_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_post(post_id):
    post = Post.query.get_or_404(post_id)
    db.session.delete(post)
    db.session.commit()
    flash('帖子已删除', 'info')
    return redirect(url_for('admin_posts'))


@app.route('/admin/categories')
@login_required
@admin_required
def admin_categories():
    form = CategoryForm()
    categories = Category.query.order_by(Category.created_at.asc()).all()
    return render_template('admin/categories.html', categories=categories, form=form)


@app.route('/admin/category/add', methods=['POST'])
@login_required
@admin_required
def add_category():
    form = CategoryForm()
    if form.validate_on_submit():
        cat = Category(name=form.name.data, description=form.description.data,
                       icon=form.icon.data or 'bi-folder')
        db.session.add(cat)
        db.session.commit()
        flash('分类已添加', 'success')
    else:
        flash('表单验证失败', 'danger')
    return redirect(url_for('admin_categories'))


@app.route('/admin/category/<int:cat_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_category(cat_id):
    cat = Category.query.get_or_404(cat_id)
    if cat.posts.count() > 0:
        flash('该分类下有帖子，无法删除', 'warning')
    else:
        db.session.delete(cat)
        db.session.commit()
        flash('分类已删除', 'info')
    return redirect(url_for('admin_categories'))


# ===================== 举报管理 =====================
@app.route('/admin/reports')
@login_required
@admin_required
def admin_reports():
    page = request.args.get('page', 1, type=int)
    status = request.args.get('status', 'pending')
    rtype = request.args.get('type', 'all')
    query = Report.query
    if status == 'pending':
        query = query.filter_by(is_handled=False)
    elif status == 'handled':
        query = query.filter_by(is_handled=True)
    if rtype == 'post':
        query = query.filter(Report.post_id != None)
    elif rtype == 'reply':
        query = query.filter(Report.reply_id != None)
    reports = query.order_by(Report.created_at.desc()).paginate(page=page, per_page=20, error_out=False)
    # 统计数据
    stats = {
        'pending': Report.query.filter_by(is_handled=False).count(),
        'handled': Report.query.filter_by(is_handled=True).count(),
        'total': Report.query.count(),
    }
    return render_template('admin/reports.html', reports=reports, status=status, rtype=rtype, stats=stats)


@app.route('/admin/report/<int:report_id>/handle', methods=['POST'])
@login_required
@admin_required
def handle_report(report_id):
    report = Report.query.get_or_404(report_id)
    action = request.form.get('action', 'dismiss')
    note = request.form.get('note', '')
    if action == 'delete_post' and report.post_id:
        post = Post.query.get(report.post_id)
        if post:
            db.session.delete(post)
    elif action == 'delete_reply' and report.reply_id:
        reply = Reply.query.get(report.reply_id)
        if reply:
            db.session.delete(reply)
    elif action == 'ban_user':
        if report.post_id:
            post = Post.query.get(report.post_id)
            if post and not post.author.is_admin:
                post.author.is_banned = True
        elif report.reply_id:
            reply = Reply.query.get(report.reply_id)
            if reply and not reply.author.is_admin:
                reply.author.is_banned = True
    report.is_handled = True
    report.handle_note = note
    report.handler_id = current_user.id
    report.handled_at = datetime.utcnow()
    db.session.commit()
    flash('举报已处理', 'success')
    return redirect(url_for('admin_reports', status=request.form.get('back_status', 'pending')))


@app.route('/admin/reports/batch', methods=['POST'])
@login_required
@admin_required
def batch_handle_reports():
    ids = request.form.getlist('report_ids')
    action = request.form.get('action', 'dismiss')
    count = 0
    for rid in ids:
        report = Report.query.get(int(rid))
        if report and not report.is_handled:
            if action == 'dismiss':
                pass
            elif action == 'delete_content':
                if report.post_id:
                    post = Post.query.get(report.post_id)
                    if post:
                        db.session.delete(post)
                elif report.reply_id:
                    reply = Reply.query.get(report.reply_id)
                    if reply:
                        db.session.delete(reply)
            report.is_handled = True
            report.handler_id = current_user.id
            report.handled_at = datetime.utcnow()
            count += 1
    db.session.commit()
    flash(f'已批量处理 {count} 条举报', 'success')
    return redirect(url_for('admin_reports'))


# ===================== 违禁词管理 =====================
@app.route('/admin/banned-words')
@login_required
@admin_required
def admin_banned_words():
    q = request.args.get('q', '').strip()
    form = BannedWordForm()
    query = BannedWord.query
    if q:
        query = query.filter(BannedWord.word.contains(q))
    words = query.order_by(BannedWord.created_at.desc()).all()
    return render_template('admin/banned_words.html', words=words, form=form, q=q)


@app.route('/admin/banned-words/add', methods=['POST'])
@login_required
@admin_required
def add_banned_word():
    form = BannedWordForm()
    if form.validate_on_submit():
        word_val = form.word.data.strip()
        existing = BannedWord.query.filter_by(word=word_val).first()
        if existing:
            flash('该违禁词已存在', 'warning')
        else:
            bw = BannedWord(word=word_val)
            db.session.add(bw)
            db.session.commit()
            flash(f'违禁词 "{bw.word}" 已添加', 'success')
    return redirect(url_for('admin_banned_words'))


@app.route('/admin/banned-words/import', methods=['POST'])
@login_required
@admin_required
def import_banned_words():
    """批量导入违禁词，换行或逗号分隔"""
    raw = request.form.get('words_text', '')
    import re as _re
    items = _re.split(r'[\n,，\s]+', raw)
    added, skipped = 0, 0
    for item in items:
        item = item.strip()
        if not item:
            continue
        if BannedWord.query.filter_by(word=item).first():
            skipped += 1
        else:
            db.session.add(BannedWord(word=item))
            added += 1
    db.session.commit()
    flash(f'批量导入完成：新增 {added} 个，跳过重复 {skipped} 个', 'success')
    return redirect(url_for('admin_banned_words'))


@app.route('/admin/banned-words/test', methods=['POST'])
@login_required
@admin_required
def test_banned_words():
    """测试文本是否触发违禁词"""
    text = request.form.get('test_text', '')
    is_ok, filtered = filter_content(text)
    return jsonify({'ok': is_ok, 'filtered': filtered, 'original': text})


@app.route('/admin/banned-words/<int:word_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_banned_word(word_id):
    bw = BannedWord.query.get_or_404(word_id)
    db.session.delete(bw)
    db.session.commit()
    flash('违禁词已删除', 'info')
    return redirect(url_for('admin_banned_words'))


# ===================== 内容审核 =====================
@app.route('/admin/content-review')
@login_required
@admin_required
def admin_content_review():
    page = request.args.get('page', 1, type=int)
    status = request.args.get('status', 'pending')
    trigger = request.args.get('trigger', 'all')
    query = ContentReview.query
    if status != 'all':
        query = query.filter_by(status=status)
    if trigger != 'all':
        query = query.filter_by(trigger=trigger)
    reviews = query.order_by(ContentReview.created_at.desc()).paginate(page=page, per_page=20, error_out=False)
    stats = {
        'pending': ContentReview.query.filter_by(status='pending').count(),
        'approved': ContentReview.query.filter_by(status='approved').count(),
        'rejected': ContentReview.query.filter_by(status='rejected').count(),
        'total': ContentReview.query.count(),
    }
    return render_template('admin/content_review.html', reviews=reviews, status=status,
                           trigger=trigger, stats=stats)


@app.route('/admin/content-review/<int:review_id>/approve', methods=['POST'])
@login_required
@admin_required
def approve_content(review_id):
    review = ContentReview.query.get_or_404(review_id)
    note = request.form.get('note', '')
    review.status = 'approved'
    review.reviewer_id = current_user.id
    review.review_note = note
    review.reviewed_at = datetime.utcnow()
    db.session.commit()
    flash('内容已通过审核', 'success')
    return redirect(url_for('admin_content_review', status='pending'))


@app.route('/admin/content-review/<int:review_id>/reject', methods=['POST'])
@login_required
@admin_required
def reject_content(review_id):
    review = ContentReview.query.get_or_404(review_id)
    note = request.form.get('note', '')
    action = request.form.get('action', 'hide')  # hide / delete
    review.status = 'rejected'
    review.reviewer_id = current_user.id
    review.review_note = note
    review.reviewed_at = datetime.utcnow()
    if action == 'delete':
        if review.post_id:
            post = Post.query.get(review.post_id)
            if post:
                db.session.delete(post)
        elif review.reply_id:
            reply = Reply.query.get(review.reply_id)
            if reply:
                db.session.delete(reply)
    db.session.commit()
    flash('内容审核已拒绝', 'info')
    return redirect(url_for('admin_content_review', status='pending'))


@app.route('/admin/content-review/add', methods=['POST'])
@login_required
@admin_required
def add_to_review():
    """手动将帖子/回复加入审核队列"""
    post_id = request.form.get('post_id', type=int)
    reply_id = request.form.get('reply_id', type=int)
    if post_id:
        existing = ContentReview.query.filter_by(post_id=post_id, status='pending').first()
        if not existing:
            db.session.add(ContentReview(post_id=post_id, trigger='manual'))
            db.session.commit()
            flash('帖子已加入审核队列', 'success')
        else:
            flash('该帖子已在审核队列中', 'info')
        return redirect(url_for('admin_posts'))
    elif reply_id:
        existing = ContentReview.query.filter_by(reply_id=reply_id, status='pending').first()
        if not existing:
            db.session.add(ContentReview(reply_id=reply_id, trigger='manual'))
            db.session.commit()
            flash('回复已加入审核队列', 'success')
        else:
            flash('该回复已在审核队列中', 'info')
    return redirect(url_for('admin_content_review'))


# ===================== 错误处理 =====================
@app.errorhandler(403)
def forbidden(e):
    return render_template('error.html', code=403, message='无权访问此页面'), 403


@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', code=404, message='页面不存在'), 404


# ===================== 初始化数据库 =====================
def init_db():
    with app.app_context():
        db.create_all()
        # 创建默认分类
        if Category.query.count() == 0:
            default_cats = [
                Category(name='心情日记', description='记录每天的心情与感受', icon='bi-journal-heart'),
                Category(name='倾诉发泄', description='有什么憋在心里，就说出来吧', icon='bi-chat-heart'),
                Category(name='暖心故事', description='分享那些让人感动的瞬间', icon='bi-heart-fill'),
                Category(name='生活日常', description='记录生活中的点点滴滴', icon='bi-house-heart'),
                Category(name='求助与支持', description='遇到困难？大家来帮你', icon='bi-people'),
                Category(name='公告通知', description='官方公告与通知', icon='bi-megaphone'),
            ]
            db.session.add_all(default_cats)
            db.session.commit()

        # 创建默认管理员
        if User.query.filter_by(is_admin=True).count() == 0:
            admin = User(username='admin', is_admin=True)
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
            print('默认管理员已创建: admin / admin123')

        # 添加默认违禁词
        if BannedWord.query.count() == 0:
            default_words = ['fuck', 'shit', '操你', '傻逼', '妈的', '滚蛋', '垃圾', '死去', 'sb', '脑残']
            for w in default_words:
                db.session.add(BannedWord(word=w))
            db.session.commit()
            print('默认违禁词已添加')


if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)
