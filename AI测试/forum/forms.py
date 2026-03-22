from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, TextAreaField, SelectField, BooleanField, SubmitField, HiddenField
from wtforms.validators import DataRequired, Length, EqualTo, ValidationError, Optional
from models import User


class RegisterForm(FlaskForm):
    username = StringField('用户名', validators=[DataRequired(), Length(2, 32)])
    password = PasswordField('密码', validators=[DataRequired(), Length(6, 64)])
    confirm = PasswordField('确认密码', validators=[DataRequired(), EqualTo('password', message='两次密码不一致')])
    captcha = StringField('验证码', validators=[DataRequired(message='请输入验证码')])
    submit = SubmitField('注册')

    def validate_username(self, field):
        if User.query.filter_by(username=field.data).first():
            raise ValidationError('用户名已存在')


class LoginForm(FlaskForm):
    username = StringField('用户名', validators=[DataRequired()])
    password = PasswordField('密码', validators=[DataRequired()])
    captcha = StringField('验证码', validators=[DataRequired(message='请输入验证码')])
    remember = BooleanField('记住我')
    submit = SubmitField('登录')


class PostForm(FlaskForm):
    title = StringField('标题', validators=[DataRequired(), Length(2, 256)])
    category_id = SelectField('分类', coerce=int, validators=[DataRequired()])
    content = TextAreaField('内容', validators=[DataRequired(), Length(10)])
    is_anonymous = BooleanField('匿名发布')
    submit = SubmitField('发布')


class ReplyForm(FlaskForm):
    content = TextAreaField('回复内容', validators=[DataRequired(), Length(2, 2000)])
    is_anonymous = BooleanField('匿名评论')
    submit = SubmitField('提交回复')


class ProfileForm(FlaskForm):
    bio = TextAreaField('个人简介', validators=[Length(0, 256)])
    submit = SubmitField('保存')


class CategoryForm(FlaskForm):
    name = StringField('分类名称', validators=[DataRequired(), Length(2, 64)])
    description = StringField('分类描述', validators=[Length(0, 256)])
    icon = StringField('图标类名', validators=[Length(0, 64)])
    submit = SubmitField('保存')


class ChangePasswordForm(FlaskForm):
    old_password = PasswordField('当前密码', validators=[DataRequired()])
    new_password = PasswordField('新密码', validators=[DataRequired(), Length(6, 64)])
    confirm = PasswordField('确认新密码', validators=[DataRequired(), EqualTo('new_password')])
    submit = SubmitField('修改密码')


class MessageForm(FlaskForm):
    content = TextAreaField('内容', validators=[DataRequired(), Length(1, 1000)])
    submit = SubmitField('发送')


class BannedWordForm(FlaskForm):
    word = StringField('违禁词', validators=[DataRequired(), Length(1, 128)])
    submit = SubmitField('添加')


class ReportForm(FlaskForm):
    reason = SelectField('举报原因', choices=[
        ('辱骂他人', '辱骂他人'),
        ('色情低俗', '色情低俗'),
        ('垃圾广告', '垃圾广告'),
        ('违法信息', '违法信息'),
        ('其他', '其他'),
    ], validators=[DataRequired()])
    submit = SubmitField('提交举报')
