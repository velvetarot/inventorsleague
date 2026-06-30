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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


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
    decision_maker = db.Column(db.String(200))
    gatekeeper = db.Column(db.String(200))
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
        return self.activities.first()

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
