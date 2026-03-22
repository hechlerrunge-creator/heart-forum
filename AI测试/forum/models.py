from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    is_banned = db.Column(db.Boolean, default=False)
    bio = db.Column(db.String(256), default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    posts = db.relationship('Post', backref='author', lazy='dynamic', foreign_keys='Post.user_id')
    replies = db.relationship('Reply', backref='author', lazy='dynamic')
    sent_messages = db.relationship('Message', foreign_keys='Message.sender_id', backref='sender', lazy='dynamic')
    received_messages = db.relationship('Message', foreign_keys='Message.receiver_id', backref='receiver', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def unread_message_count(self):
        return Message.query.filter_by(receiver_id=self.id, is_read=False, is_deleted_by_receiver=False).count()

    def __repr__(self):
        return f'<User {self.username}>'


class Category(db.Model):
    __tablename__ = 'categories'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False)
    description = db.Column(db.String(256), default='')
    icon = db.Column(db.String(64), default='bi-folder')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    posts = db.relationship('Post', backref='category', lazy='dynamic')

    def __repr__(self):
        return f'<Category {self.name}>'


class Post(db.Model):
    __tablename__ = 'posts'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(256), nullable=False)
    content = db.Column(db.Text, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=False)
    is_anonymous = db.Column(db.Boolean, default=False)  # 匿名发帖
    is_pinned = db.Column(db.Boolean, default=False)
    is_locked = db.Column(db.Boolean, default=False)
    views = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    replies = db.relationship('Reply', backref='post', lazy='dynamic', cascade='all, delete-orphan')
    hugs = db.relationship('Hug', backref='post', lazy='dynamic', cascade='all, delete-orphan')
    reports = db.relationship('Report', backref='post', lazy='dynamic', cascade='all, delete-orphan')

    @property
    def reply_count(self):
        return self.replies.count()

    @property
    def hug_count(self):
        return self.hugs.count()

    def display_author(self):
        if self.is_anonymous:
            return '匿名用户'
        return self.author.username

    def __repr__(self):
        return f'<Post {self.title}>'


class Reply(db.Model):
    __tablename__ = 'replies'
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=False)
    is_anonymous = db.Column(db.Boolean, default=False)  # 匿名评论
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    hug_replies = db.relationship('HugReply', backref='reply', lazy='dynamic', cascade='all, delete-orphan')

    @property
    def hug_count(self):
        return self.hug_replies.count()

    def display_author(self):
        if self.is_anonymous:
            return '匿名用户'
        return self.author.username

    def __repr__(self):
        return f'<Reply {self.id}>'


class Hug(db.Model):
    """帖子拥抱（类点赞）"""
    __tablename__ = 'hugs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('user_id', 'post_id', name='unique_hug'),)


class HugReply(db.Model):
    """回复拥抱"""
    __tablename__ = 'hug_replies'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    reply_id = db.Column(db.Integer, db.ForeignKey('replies.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('user_id', 'reply_id', name='unique_hug_reply'),)


class Message(db.Model):
    """私信"""
    __tablename__ = 'messages'
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    is_deleted_by_sender = db.Column(db.Boolean, default=False)
    is_deleted_by_receiver = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Message {self.id}>'


class BannedWord(db.Model):
    """违禁词"""
    __tablename__ = 'banned_words'
    id = db.Column(db.Integer, primary_key=True)
    word = db.Column(db.String(128), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<BannedWord {self.word}>'


class Report(db.Model):
    """举报"""
    __tablename__ = 'reports'
    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=True)
    reply_id = db.Column(db.Integer, db.ForeignKey('replies.id'), nullable=True)
    reason = db.Column(db.String(256), nullable=False)
    is_handled = db.Column(db.Boolean, default=False)
    handle_note = db.Column(db.String(512), default='')   # 处理备注
    handler_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # 处理人
    handled_at = db.Column(db.DateTime, nullable=True)    # 处理时间
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    reporter = db.relationship('User', foreign_keys=[reporter_id])
    reported_reply = db.relationship('Reply', foreign_keys=[reply_id])
    handler = db.relationship('User', foreign_keys=[handler_id])

    def __repr__(self):
        return f'<Report {self.id}>'


class ContentReview(db.Model):
    """内容审核队列"""
    __tablename__ = 'content_reviews'
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=True)
    reply_id = db.Column(db.Integer, db.ForeignKey('replies.id'), nullable=True)
    trigger = db.Column(db.String(64), default='report')  # report / keyword / manual
    status = db.Column(db.String(16), default='pending')  # pending / approved / rejected
    reviewer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    review_note = db.Column(db.String(512), default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_at = db.Column(db.DateTime, nullable=True)

    post = db.relationship('Post', foreign_keys=[post_id])
    reply = db.relationship('Reply', foreign_keys=[reply_id])
    reviewer = db.relationship('User', foreign_keys=[reviewer_id])

    def __repr__(self):
        return f'<ContentReview {self.id}>'
