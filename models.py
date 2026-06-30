from datetime import datetime, date
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(256))
    last_seen = db.Column(db.DateTime)
    role = db.Column(db.String(20), default='user')  # admin / manager / user
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_online(self):
        if not self.last_seen:
            return False
        return (datetime.utcnow() - self.last_seen).total_seconds() < 300

    @property
    def is_admin(self):
        return self.role == 'admin'

    @property
    def is_manager(self):
        return self.role in ('admin', 'manager')

    @property
    def can_delete(self):
        return self.role in ('admin', 'manager')

    @property
    def can_manage_users(self):
        return self.role == 'admin'


class Message(db.Model):
    __tablename__ = 'messages'
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    sender = db.relationship('User', foreign_keys=[sender_id], backref='sent_messages')
    recipient = db.relationship('User', foreign_keys=[recipient_id], backref='received_messages')


class School(db.Model):
    __tablename__ = 'schools'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(30))
    website = db.Column(db.String(200))
    main_email = db.Column(db.String(150))
    headteacher = db.Column(db.String(200))
    account_type = db.Column(db.String(100))
    phase = db.Column(db.String(50))          # Primary / Secondary
    pupils = db.Column(db.Integer)
    fsm_percent = db.Column(db.Float)
    affluence_score = db.Column(db.Float)
    est_club_pupils_low = db.Column(db.Integer)
    est_club_pupils_high = db.Column(db.Integer)
    term_revenue = db.Column(db.Float)
    term_profit = db.Column(db.Float)
    annual_revenue = db.Column(db.Float)
    rating = db.Column(db.Float)
    final_score = db.Column(db.Float)
    priority_tier = db.Column(db.String(10))   # A / B / C
    call_action = db.Column(db.String(100))
    city = db.Column(db.String(100))
    postcode = db.Column(db.String(20))
    billing_address = db.Column(db.String(300))
    description = db.Column(db.Text)
    # Pipeline fields
    after_school_club_status = db.Column(db.String(50))
    assembly_opportunity = db.Column(db.String(50))
    assembly_date = db.Column(db.Date)
    summer_camp_status = db.Column(db.String(50))
    decision_maker         = db.Column(db.String(200))
    gatekeeper             = db.Column(db.String(200))
    business_manager_name  = db.Column(db.String(200))
    business_manager_email = db.Column(db.String(150))
    stage = db.Column(db.String(50), default='New')  # New / Contacted / Interested / Demo Booked / Won / Lost
    school_notes = db.Column(db.Text)  # quick freetext notes separate from activity log
    won = db.Column(db.Boolean, default=False)
    digital_flyer_sent = db.Column(db.Boolean, default=False)
    physical_flyer_sent = db.Column(db.Boolean, default=False)
    # Meta
    zoho_id = db.Column(db.String(50), unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    activities = db.relationship('Activity', backref='school', lazy='dynamic',
                                 order_by='Activity.created_at.desc()')

    @property
    def last_activity(self):
        last_act = self.activities.first()
        last_email = EmailLog.query.filter_by(school_id=self.id).order_by(EmailLog.sent_at.desc()).first()
        if last_act and last_email:
            return last_act if last_act.created_at >= last_email.sent_at else last_email
        return last_act or last_email

    @property
    def next_followup(self):
        return Activity.query.filter_by(school_id=self.id).filter(
            Activity.follow_up_date >= date.today()
        ).order_by(Activity.follow_up_date).first()

    @property
    def overdue_followups(self):
        return Activity.query.filter_by(school_id=self.id).filter(
            Activity.follow_up_date < date.today(),
            Activity.follow_up_complete == False
        ).count()


class Parent(db.Model):
    __tablename__ = 'parents'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(30))
    email = db.Column(db.String(150))
    child_name = db.Column(db.String(200))
    child_age = db.Column(db.Integer)
    enquiry_type = db.Column(db.String(100))  # Birthday Party, Holiday Camp, Private Tuition, etc.
    status = db.Column(db.String(50), default='New Enquiry')  # New Enquiry, Quoted, Booked, Done, Lost
    event_date = db.Column(db.Date)
    notes = db.Column(db.Text)
    source = db.Column(db.String(100))  # How they found us
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    contact_log = db.relationship('ParentActivity', backref='parent', lazy='dynamic',
                                  order_by='ParentActivity.created_at.desc()')


class ParentActivity(db.Model):
    __tablename__ = 'parent_activities'
    id = db.Column(db.Integer, primary_key=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('parents.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    type = db.Column(db.String(30), nullable=False)
    outcome = db.Column(db.String(100))
    notes = db.Column(db.Text)
    next_action = db.Column(db.String(300))
    follow_up_date = db.Column(db.Date)
    follow_up_complete = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='parent_activities')


class Attachment(db.Model):
    __tablename__ = 'attachments'
    id = db.Column(db.Integer, primary_key=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('parents.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), nullable=False)
    file_size = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='attachments')


class EmailTemplate(db.Model):
    __tablename__ = 'email_templates'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    body_html = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class EmailLog(db.Model):
    __tablename__ = 'email_logs'
    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('parents.id'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    to_email = db.Column(db.String(150), nullable=False)
    to_name = db.Column(db.String(200))
    subject = db.Column(db.String(200))
    body_html = db.Column(db.Text)
    template_name = db.Column(db.String(100))
    brevo_message_id = db.Column(db.String(200), unique=True)
    status = db.Column(db.String(30), default='sent')  # sent / delivered / opened / bounced / error
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)
    delivered_at = db.Column(db.DateTime)
    opened_at = db.Column(db.DateTime)
    bounced_at = db.Column(db.DateTime)

    school = db.relationship('School', backref='emails')
    parent = db.relationship('Parent', backref='emails')
    user = db.relationship('User', backref='emails')

    # Compatibility props so EmailLog can be used wherever Activity is expected
    @property
    def type(self):
        return 'email'

    @property
    def outcome(self):
        return self.status.title() if self.status else 'Sent'

    @property
    def notes(self):
        return f'Email: {self.subject}'

    @property
    def created_at(self):
        return self.sent_at

    @property
    def error_message(self):
        return None


class Activity(db.Model):
    __tablename__ = 'activities'
    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    type = db.Column(db.String(30), nullable=False)  # call / email / meeting / note
    outcome = db.Column(db.String(100))
    notes = db.Column(db.Text)
    next_action = db.Column(db.String(300))
    follow_up_date = db.Column(db.Date)
    follow_up_complete = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='activities')
