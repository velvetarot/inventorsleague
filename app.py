import os
from datetime import date, datetime
from flask import Flask, render_template, redirect, url_for, request, flash, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from sqlalchemy import or_, func
from models import db, User, School, Activity
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-change-me')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///crm.db')
if app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgres://'):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace(
        'postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access the CRM.'


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form['email'].strip().lower()).first()
        if user and user.check_password(request.form['password']):
            login_user(user)
            return redirect(request.args.get('next') or url_for('dashboard'))
        flash('Invalid email or password.', 'danger')
    return render_template('auth/login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.route('/')
@login_required
def dashboard():
    today = date.today()

    overdue = Activity.query.filter(
        Activity.follow_up_date < today,
        Activity.follow_up_complete == False
    ).join(School).order_by(Activity.follow_up_date).all()

    due_today = Activity.query.filter(
        Activity.follow_up_date == today,
        Activity.follow_up_complete == False
    ).join(School).order_by(School.name).all()

    due_soon = Activity.query.filter(
        Activity.follow_up_date > today,
        Activity.follow_up_complete == False
    ).join(School).order_by(Activity.follow_up_date).limit(10).all()

    recent = Activity.query.order_by(Activity.created_at.desc()).limit(10).all()

    stats = {
        'total_schools': School.query.count(),
        'called': School.query.join(Activity).distinct().count(),
        'won': School.query.filter_by(won=True).count(),
        'overdue': len(overdue),
    }

    return render_template('dashboard.html',
                           overdue=overdue, due_today=due_today,
                           due_soon=due_soon, recent=recent, stats=stats, today=today)


# ── Schools ───────────────────────────────────────────────────────────────────

@app.route('/schools')
@login_required
def schools():
    q = request.args.get('q', '').strip()
    phase = request.args.get('phase', '')
    tier = request.args.get('tier', '')
    club_status = request.args.get('club_status', '')
    sort = request.args.get('sort', 'name')

    query = School.query

    if q:
        query = query.filter(or_(
            School.name.ilike(f'%{q}%'),
            School.city.ilike(f'%{q}%'),
            School.headteacher.ilike(f'%{q}%'),
            School.main_email.ilike(f'%{q}%'),
        ))
    if phase:
        query = query.filter(School.phase == phase)
    if tier:
        query = query.filter(School.priority_tier == tier)
    if club_status:
        query = query.filter(School.after_school_club_status == club_status)

    sort_map = {
        'name': School.name,
        'priority': School.rating.desc(),
        'revenue': School.term_revenue.desc(),
        'pupils': School.pupils.desc(),
    }
    query = query.order_by(sort_map.get(sort, School.name))

    schools_list = query.all()

    phases = [r[0] for r in db.session.query(School.phase).distinct() if r[0]]
    tiers = [r[0] for r in db.session.query(School.priority_tier).distinct() if r[0]]
    club_statuses = [r[0] for r in db.session.query(School.after_school_club_status).distinct() if r[0]]

    return render_template('schools/index.html',
                           schools=schools_list, q=q, phase=phase,
                           tier=tier, club_status=club_status, sort=sort,
                           phases=sorted(phases), tiers=sorted(tiers),
                           club_statuses=sorted(club_statuses))


@app.route('/schools/<int:school_id>')
@login_required
def school_detail(school_id):
    school = School.query.get_or_404(school_id)
    activities = school.activities.order_by(Activity.created_at.desc()).all()
    return render_template('schools/detail.html', school=school, activities=activities)


@app.route('/schools/<int:school_id>/edit', methods=['GET', 'POST'])
@login_required
def school_edit(school_id):
    school = School.query.get_or_404(school_id)
    if request.method == 'POST':
        school.name = request.form['name']
        school.phone = request.form.get('phone', '')
        school.main_email = request.form.get('main_email', '')
        school.headteacher = request.form.get('headteacher', '')
        school.website = request.form.get('website', '')
        school.phase = request.form.get('phase', '')
        school.account_type = request.form.get('account_type', '')
        school.city = request.form.get('city', '')
        school.postcode = request.form.get('postcode', '')
        school.decision_maker = request.form.get('decision_maker', '')
        school.gatekeeper = request.form.get('gatekeeper', '')
        school.after_school_club_status = request.form.get('after_school_club_status', '')
        school.assembly_opportunity = request.form.get('assembly_opportunity', '')
        school.summer_camp_status = request.form.get('summer_camp_status', '')
        school.digital_flyer_sent = 'digital_flyer_sent' in request.form
        school.physical_flyer_sent = 'physical_flyer_sent' in request.form
        school.won = 'won' in request.form
        school.description = request.form.get('description', '')
        school.updated_at = datetime.utcnow()
        db.session.commit()
        flash('School updated.', 'success')
        return redirect(url_for('school_detail', school_id=school.id))
    return render_template('schools/edit.html', school=school)


@app.route('/schools/new', methods=['GET', 'POST'])
@login_required
def school_new():
    if request.method == 'POST':
        school = School(
            name=request.form['name'],
            phone=request.form.get('phone', ''),
            main_email=request.form.get('main_email', ''),
            headteacher=request.form.get('headteacher', ''),
            website=request.form.get('website', ''),
            phase=request.form.get('phase', ''),
            city=request.form.get('city', ''),
            postcode=request.form.get('postcode', ''),
        )
        db.session.add(school)
        db.session.commit()
        flash('School added.', 'success')
        return redirect(url_for('school_detail', school_id=school.id))
    return render_template('schools/edit.html', school=None)


# ── Activities ────────────────────────────────────────────────────────────────

@app.route('/schools/<int:school_id>/activity/new', methods=['GET', 'POST'])
@login_required
def activity_new(school_id):
    school = School.query.get_or_404(school_id)
    if request.method == 'POST':
        follow_up_raw = request.form.get('follow_up_date', '').strip()
        follow_up = datetime.strptime(follow_up_raw, '%Y-%m-%d').date() if follow_up_raw else None

        activity = Activity(
            school_id=school.id,
            user_id=current_user.id,
            type=request.form['type'],
            outcome=request.form.get('outcome', ''),
            notes=request.form.get('notes', ''),
            next_action=request.form.get('next_action', ''),
            follow_up_date=follow_up,
        )
        db.session.add(activity)

        # Update school pipeline fields from the form
        if request.form.get('club_status'):
            school.after_school_club_status = request.form['club_status']
        if request.form.get('assembly_opportunity'):
            school.assembly_opportunity = request.form['assembly_opportunity']
        if 'won' in request.form:
            school.won = True
        school.updated_at = datetime.utcnow()

        db.session.commit()
        flash('Activity logged.', 'success')
        return redirect(url_for('school_detail', school_id=school.id))
    return render_template('schools/activity_new.html', school=school)


@app.route('/activity/<int:activity_id>/complete', methods=['POST'])
@login_required
def activity_complete(activity_id):
    activity = Activity.query.get_or_404(activity_id)
    activity.follow_up_complete = True
    db.session.commit()
    return jsonify({'ok': True})


# ── Admin ─────────────────────────────────────────────────────────────────────

@app.route('/admin/users', methods=['GET', 'POST'])
@login_required
def admin_users():
    if request.method == 'POST':
        existing = User.query.filter_by(email=request.form['email'].strip().lower()).first()
        if existing:
            flash('Email already exists.', 'danger')
        else:
            user = User(
                name=request.form['name'],
                email=request.form['email'].strip().lower(),
            )
            user.set_password(request.form['password'])
            db.session.add(user)
            db.session.commit()
            flash(f'User {user.name} created.', 'success')
    users = User.query.order_by(User.name).all()
    return render_template('auth/users.html', users=users)


# ── Init ──────────────────────────────────────────────────────────────────────

def create_tables():
    with app.app_context():
        db.create_all()
        if not User.query.first():
            admin = User(name='Admin', email='admin@inventorsleague.co.uk')
            admin.set_password('changeme123')
            db.session.add(admin)
            db.session.commit()
            print('Created default admin user: admin@inventorsleague.co.uk / changeme123')


if __name__ == '__main__':
    create_tables()
    app.run(debug=True)
