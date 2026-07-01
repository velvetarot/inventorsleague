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
    last_contacted = db.Column(db.DateTime)  # updated on every activity or email
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


class Booking(db.Model):
    __tablename__ = 'bookings'
    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    booking_type = db.Column(db.String(50), nullable=False)  # Birthday Party / Workshop / After School Club
    title = db.Column(db.String(200), nullable=False)
    client_name = db.Column(db.String(200))   # for non-school bookings
    client_email = db.Column(db.String(150))
    client_phone = db.Column(db.String(30))
    event_date = db.Column(db.Date)
    end_date = db.Column(db.Date)             # for term clubs: last session date
    num_children = db.Column(db.Integer)
    num_weeks = db.Column(db.Integer)         # for term clubs
    price_per_child = db.Column(db.Float)     # per session for clubs, flat per child for parties
    flat_fee = db.Column(db.Float)            # alternative to per-child pricing
    notes = db.Column(db.Text)
    status = db.Column(db.String(30), default='Enquiry')  # Enquiry / Confirmed / Invoiced / Paid / Cancelled
    invoice_number = db.Column(db.String(50))
    invoice_sent_at = db.Column(db.DateTime)
    paid_at = db.Column(db.DateTime)
    amount_paid = db.Column(db.Float)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    school = db.relationship('School', backref='bookings')
    user = db.relationship('User', backref='bookings')
    payments = db.relationship('Payment', backref='booking', lazy='dynamic',
                               order_by='Payment.paid_at.desc()')

    @property
    def total_revenue(self):
        if self.flat_fee:
            return self.flat_fee
        if self.booking_type == 'After School Club':
            return (self.num_children or 0) * (self.num_weeks or 0) * (self.price_per_child or 0)
        return (self.num_children or 0) * (self.price_per_child or 0)

    @property
    def total_paid(self):
        return sum(p.amount for p in self.payments)

    @property
    def outstanding(self):
        return max(0, (self.total_revenue or 0) - self.total_paid)

    @property
    def is_overdue(self):
        if self.status in ('Paid', 'Cancelled'):
            return False
        if self.status == 'Invoiced' and self.invoice_sent_at:
            return (datetime.utcnow() - self.invoice_sent_at).days > 30
        return False


class Payment(db.Model):
    __tablename__ = 'payments'
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey('bookings.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    amount = db.Column(db.Float, nullable=False)
    method = db.Column(db.String(30), default='BACS')  # BACS / Card / Cash / Cheque
    reference = db.Column(db.String(100))
    notes = db.Column(db.String(300))
    paid_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='payments')


class Programme(db.Model):
    """A club, camp, workshop or activity that parents can book onto."""
    __tablename__ = 'programmes'
    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(100), unique=True, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    activity_type = db.Column(db.String(50))  # After School Club / Holiday Camp / Workshop / Birthday Party
    location_name = db.Column(db.String(200))
    location_address = db.Column(db.String(300))
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    days_of_week = db.Column(db.String(50))  # "Mon,Tue,Wed,Thu,Fri"
    start_time = db.Column(db.String(10))
    end_time = db.Column(db.String(10))
    min_age_years = db.Column(db.Integer)
    max_age_years = db.Column(db.Integer)
    capacity_per_session = db.Column(db.Integer, default=20)
    price_per_session = db.Column(db.Float, default=0)
    is_active = db.Column(db.Boolean, default=True)
    is_public = db.Column(db.Boolean, default=True)
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    school = db.relationship('School', backref='programmes')
    sessions = db.relationship('ProgrammeSession', backref='programme', lazy='dynamic',
                               order_by='ProgrammeSession.date')
    enrolments = db.relationship('Enrolment', backref='programme', lazy='dynamic')
    promo_codes = db.relationship('PromoCode', backref='programme', lazy='dynamic')

    @property
    def days_list(self):
        return [d.strip() for d in (self.days_of_week or '').split(',') if d.strip()]

    @property
    def total_paid_enrolments(self):
        return self.enrolments.filter_by(payment_status='paid').count()

    def generate_sessions(self):
        day_map = {'Mon': 0, 'Tue': 1, 'Wed': 2, 'Thu': 3, 'Fri': 4, 'Sat': 5, 'Sun': 6}
        days = [day_map[d] for d in self.days_list if d in day_map]
        if not self.start_date or not self.end_date:
            return
        current = self.start_date
        while current <= self.end_date:
            if current.weekday() in days:
                existing = ProgrammeSession.query.filter_by(
                    programme_id=self.id, date=current).first()
                if not existing:
                    db.session.add(ProgrammeSession(
                        programme_id=self.id,
                        date=current,
                        start_time=self.start_time,
                        end_time=self.end_time,
                        capacity=self.capacity_per_session,
                    ))
            from datetime import timedelta
            current += timedelta(days=1)


class ProgrammeSession(db.Model):
    __tablename__ = 'programme_sessions'
    id = db.Column(db.Integer, primary_key=True)
    programme_id = db.Column(db.Integer, db.ForeignKey('programmes.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.String(10))
    end_time = db.Column(db.String(10))
    capacity = db.Column(db.Integer, default=20)
    cancelled = db.Column(db.Boolean, default=False)

    @property
    def spots_taken(self):
        return db.session.query(enrolment_sessions).filter_by(session_id=self.id).join(
            Enrolment, Enrolment.id == enrolment_sessions.c.enrolment_id
        ).filter(Enrolment.payment_status == 'paid').count()

    @property
    def spots_available(self):
        return max(0, (self.capacity or 0) - self.spots_taken)

    @property
    def is_full(self):
        return self.spots_available == 0


enrolment_sessions = db.Table('enrolment_sessions',
    db.Column('enrolment_id', db.Integer, db.ForeignKey('enrolments.id'), primary_key=True),
    db.Column('session_id', db.Integer, db.ForeignKey('programme_sessions.id'), primary_key=True),
)


class Enrolment(db.Model):
    __tablename__ = 'enrolments'
    id = db.Column(db.Integer, primary_key=True)
    programme_id = db.Column(db.Integer, db.ForeignKey('programmes.id'), nullable=False)
    parent_name = db.Column(db.String(200), nullable=False)
    parent_email = db.Column(db.String(150), nullable=False)
    parent_phone = db.Column(db.String(30))
    child_name = db.Column(db.String(200), nullable=False)
    child_dob = db.Column(db.Date)
    emergency_name = db.Column(db.String(200))
    emergency_phone = db.Column(db.String(30))
    medical_notes = db.Column(db.Text)
    marketing_consent = db.Column(db.Boolean, default=False)
    photo_consent = db.Column(db.Boolean, default=False)
    promo_code_id = db.Column(db.Integer, db.ForeignKey('promo_codes.id'), nullable=True)
    subtotal = db.Column(db.Float, default=0)
    discount_amount = db.Column(db.Float, default=0)
    total = db.Column(db.Float, default=0)
    stripe_session_id = db.Column(db.String(200), unique=True)
    stripe_payment_intent = db.Column(db.String(200))
    payment_status = db.Column(db.String(20), default='pending')  # pending/paid/failed/refunded
    paid_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    sessions = db.relationship('ProgrammeSession', secondary=enrolment_sessions, lazy='subquery')
    promo_code = db.relationship('PromoCode', backref='enrolments')


class PromoCode(db.Model):
    __tablename__ = 'promo_codes'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    discount_type = db.Column(db.String(10), default='percent')  # percent / fixed
    discount_value = db.Column(db.Float, nullable=False)
    max_uses = db.Column(db.Integer)
    programme_id = db.Column(db.Integer, db.ForeignKey('programmes.id'), nullable=True)
    valid_from = db.Column(db.Date)
    valid_until = db.Column(db.Date)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def uses_count(self):
        return len([e for e in self.enrolments if e.payment_status == 'paid'])

    def is_valid_for(self, programme_id=None):
        if not self.active:
            return False, 'This promo code is not active.'
        if self.max_uses and self.uses_count >= self.max_uses:
            return False, 'This promo code has reached its maximum uses.'
        today = date.today()
        if self.valid_from and today < self.valid_from:
            return False, 'This promo code is not yet valid.'
        if self.valid_until and today > self.valid_until:
            return False, 'This promo code has expired.'
        if self.programme_id and programme_id and self.programme_id != programme_id:
            return False, 'This promo code is not valid for this activity.'
        return True, 'Valid'

    def calculate_discount(self, subtotal):
        if self.discount_type == 'percent':
            return round(subtotal * self.discount_value / 100, 2)
        return min(self.discount_value, subtotal)


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
