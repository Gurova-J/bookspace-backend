import base64
import io
import random
import string

from PIL import Image
from flask import render_template, make_response, send_file, abort
from flask_mail import Message
from sqlalchemy.exc import SQLAlchemyError

from bookspace.core.app import db, api, mail
from flask_restful import Resource, reqparse

from bookspace.models import User, UsersBooks, Stats, Books, Reviews, Tokens
from sqlalchemy import func, desc, and_, or_
import datetime

_BAD_REQUEST = {'message': 'unvalid data', 'status': 400}
_GOOD_REQUEST = {'message': 'ok', 'status': 200}

session = db.session


class Login(Resource):

    def __init__(self):
        self.parser = reqparse.RequestParser()
        self.parser.add_argument('email', required=True)
        self.parser.add_argument('password', required=True)

    def post(self):
        args = self.parser.parse_args()
        email = args['email']
        password = args['password']

        user = User.query.filter_by(email=email).first()
        if user is None:
            return {'status': 404,
                    'message': f'User with email {email} does not exist'}
        else:
            if user.check_password(password):
                check_login = Tokens.query.filter_by(user_id=user.id).first()
                if check_login is None:
                    token = user.generate_auth_token(expiration=10000)
                    tkn = str(token)
                    tkn = tkn[2:len(tkn) - 1]
                    new = Tokens(token=tkn, user_id=user.id)
                    session.add(new)
                    try:
                        session.commit()
                    except SQLAlchemyError:
                        session.rollback()

                    return {'message': 'ok', 'status': 200, 'Bearer': tkn}, {'Bearer': token}
                else:
                    return {'message': 'User already logged in', 'status': '400'}
            return _BAD_REQUEST


api.add_resource(Login, '/login')


class Register(Resource):
    def __init__(self):
        self.parser = reqparse.RequestParser()
        self.parser.add_argument('password', required=True)
        self.parser.add_argument('email', required=True)

    def post(self):
        args = self.parser.parse_args()
        email = args['email']
        password = args['password']

        user = User.query.filter_by(email=email).first()
        if user is not None:
            return {'status': 400,
                    'message': f'User with email {email} already exists'}
        elif email is not None and password is not None:
            username = email[0:email.find('@')]
            user = User(
                email=email,
                username=username,
            )
            user.set_password(password)
            with Image.open('bookspace/static/images/avatar.png') as img:
                output = io.BytesIO()
                img.save(output, format='png')
                image_data = output.getvalue()
                user.image = image_data
            session.add(user)
            try:
                session.commit()
            except SQLAlchemyError:
                session.rollback()
            status = Stats(
                user_id=user.id
            )
            session.add(status)
            try:
                session.commit()
            except SQLAlchemyError:
                session.rollback()
            return {'message': 'Successfully created', 'status': 201}
        else:
            return _BAD_REQUEST


api.add_resource(Register, '/register')


class UserProfile(Resource):
    def __init__(self):
        self.parser = reqparse.RequestParser()
        self.parser.add_argument('password')
        self.parser.add_argument('username')
        self.parser.add_argument('quote')
        self.parser.add_argument('Authorization', location='headers')

    def get(self):
        args = self.parser.parse_args()
        if args['Authorization'] is None:
            return {'message': 'Unauthorized', 'status': 401}
        token = args['Authorization'].split(' ')[1]
        if User.verify_auth_token(token) is None:
            return {'message': 'Unauthorized', 'status': 401}
        user_id = User.verify_auth_token(token)['user_id']
        user = User.query.get(user_id)
        if user is None:
            return _BAD_REQUEST
        else:
            user_stats = Stats.query.filter_by(user_id=user.id).first()
            done = UsersBooks.query.filter_by(user_id=user.id).filter_by(
                list='DN').count()
            progress = UsersBooks.query.filter_by(user_id=user.id).filter_by(
                list='IP').count()
            future = UsersBooks.query.filter_by(user_id=user.id).filter_by(
                list='WR').count()
            user_profile = {
                "username": user.username,
                "email": user.email,
                "week": user_stats.week,
                "year": user_stats.year,
                "month": user_stats.month,
                "done": done,
                "progress": progress,
                "future": future,
                "role": user.role.value,
                "quote": user.quote
            }
        return {'user': user_profile, 'status': 200}

    def put(self):
        args = self.parser.parse_args()
        username = args.get('username')
        password = args.get('password')
        quote = args.get('quote')

        if args['Authorization'] is None:
            return {'message': 'Unauthorized', 'status': 401}
        token = args['Authorization'].split(' ')[1]
        if User.verify_auth_token(token) is None:
            return {'message': 'Unauthorized', 'status': 401}
        user_id = User.verify_auth_token(token)['user_id']
        user = User.query.get(user_id)
        if user is None:
            return _BAD_REQUEST
        else:
            if username:
                user.username = username
            if quote:
                user.quote = quote
            if password:
                user.set_password(password)
            try:
                session.commit()
            except SQLAlchemyError:
                session.rollback()
            return {'message': 'successfully updated', 'status': 200}


api.add_resource(UserProfile, '/profile')


class UserProfilePhoto(Resource):
    def __init__(self):
        self.parser = reqparse.RequestParser()
        self.parser.add_argument('image')
        self.parser.add_argument('Authorization', location='headers')

    def get(self):
        args = self.parser.parse_args()
        if args['Authorization'] is None:
            return {'message': 'Unauthorized', 'status': 401}

        token = args.get('Authorization').split(' ')[1]
        if not token or not User.verify_auth_token(token):
            abort(401, 'Unauthorized')
        user_id = User.verify_auth_token(token)['user_id']
        user = User.query.get(user_id)
        if user is None:
            return _BAD_REQUEST
        else:
            if user.image:
                image = 'data:image/png;base64,' + base64.b64encode(user.image).decode("utf-8")
            else:
                image = user.avatar()
            return {'image': image}

    def post(self):
        args = self.parser.parse_args()
        photo = args.get('image')
        token = args.get('Authorization').split(' ')[1]

        if not token or not User.verify_auth_token(token):
            abort(401, 'Unauthorized')
        if not photo:
            abort(400, 'Photo was not provided')

        user_id = User.verify_auth_token(token)['user_id']
        user = User.query.get(user_id)
        try:
            b64photo = photo.split('base64,')[1]
            photo_data = base64.b64decode(b64photo)
            user.image = photo_data
            db.session.add(user)
            try:
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
            return {'message': 'Image was uploaded', 'status': 201}
        except IOError as e:
            abort(400, 'Could not process given image')
        except SQLAlchemyError as e:
            abort(400, f'Could not save image due to {e}')
        except Exception as e:
            abort(400, f'An error occurred')


api.add_resource(UserProfilePhoto, '/profile/image')


class Statistics(Resource):
    def __init__(self):
        self.parser = reqparse.RequestParser()
        self.parser.add_argument('range')
        self.parser.add_argument('week')
        self.parser.add_argument('month')
        self.parser.add_argument('year')

        self.parser.add_argument('Authorization', location='headers')

    def get(self):
        args = self.parser.parse_args()
        if args['Authorization'] is None:
            return {'message': 'Unauthorized', 'status': 401}

        token = args['Authorization'].split(' ')[1]
        range = args['range']
        if User.verify_auth_token(token) is None:
            return {'message': 'Unauthorized', 'status': 401}
        user_id = User.verify_auth_token(token)['user_id']
        user = User.query.get(user_id)
        status = Stats.query.filter_by(user_id=user.id).first()
        range_books = []

        date_to = datetime.date.today()
        date_from = datetime.date.today()
        if range == 'week':
            date_from = datetime.date.today() - datetime.timedelta(days=7)
        elif range == 'month':
            date_from = datetime.date.today() - datetime.timedelta(days=30)
        elif range == 'year':
            date_from = datetime.date.today() - datetime.timedelta(days=365)

        books = UsersBooks.query.filter_by(user_id=user.id).\
            filter(and_(func.date(UsersBooks.data_added) >= date_from),
                   func.date(UsersBooks.data_added) <= date_to).\
            filter_by(list='DN').all()

        count = len(books)
        if count == 0:
            fav_author = '-'
            fav_genre = '-'
        else:
            for book in books:
                range_books.append(book.books_id)

            fav_author = Books.query.with_entities(Books.author,
                                                   func.count(Books.author)). \
                group_by(Books.author). \
                filter(Books.id.in_(range_books)). \
                order_by(desc(func.count(Books.author))). \
                first()[0]

            fav_genre = Books.query.with_entities(Books.genre,
                                                  func.count(Books.genre)). \
                group_by(Books.genre). \
                filter(Books.id.in_(range_books)).order_by(
                desc(func.count(Books.genre))). \
                first()[0]

        divide = 0
        if range == 'week':
            divide = status.week
        elif range == 'month':
            divide = status.month
        elif range == 'year':
            divide = status.year

        if divide > 0:
            percent = f'{round(count * 100 / divide, 2)}%'
        else:
            percent = 'no info provided'
        info = {
            "count": count,
            "fav_author": fav_author,
            "fav_genre": fav_genre,
        }
        plan = {
            "plan": divide,
            "count": count,
            "percent": percent
        }
        return {"info": info, "plan": plan, 'status': 200}

##FIXME: figure out what to do with get request that unable to send body
    def post(self):
        args = self.parser.parse_args()
        if args['Authorization'] is None:
            return {'message': 'Unauthorized', 'status': 401}

        token = args['Authorization'].split(' ')[1]
        range = args['range']
        if User.verify_auth_token(token) is None:
            return {'message': 'Unauthorized', 'status': 401}
        user_id = User.verify_auth_token(token)['user_id']
        user = User.query.get(user_id)
        status = Stats.query.filter_by(user_id=user.id).first()
        range_books = []

        date_to = datetime.date.today()
        date_from = datetime.date.today()
        if range == 'week':
            date_from = datetime.date.today() - datetime.timedelta(days=7)
        elif range == 'month':
            date_from = datetime.date.today() - datetime.timedelta(days=30)
        elif range == 'year':
            date_from = datetime.date.today() - datetime.timedelta(days=365)

        books = UsersBooks.query.filter_by(user_id=user.id).\
            filter(and_(func.date(UsersBooks.data_added) >= date_from),
                   func.date(UsersBooks.data_added) <= date_to).\
            filter_by(list='DN').all()

        count = len(books)
        if count == 0:
            fav_author = '-'
            fav_genre = '-'
        else:
            for book in books:
                range_books.append(book.books_id)

            fav_author = Books.query.with_entities(Books.author,
                                                   func.count(Books.author)). \
                group_by(Books.author). \
                filter(Books.id.in_(range_books)). \
                order_by(desc(func.count(Books.author))). \
                first()[0]

            fav_genre = Books.query.with_entities(Books.genre,
                                                  func.count(Books.genre)). \
                group_by(Books.genre). \
                filter(Books.id.in_(range_books)).order_by(
                desc(func.count(Books.genre))). \
                first()[0]

        divide = 0
        if range == 'week':
            divide = status.week
        elif range == 'month':
            divide = status.month
        elif range == 'year':
            divide = status.year

        if divide > 0:
            percent = f'{round(count * 100 / divide, 2)}%'
        else:
            percent = 'no info provided'
        info = {
            "count": count,
            "fav_author": fav_author,
            "fav_genre": fav_genre,
        }
        plan = {
            "plan": divide,
            "count": count,
            "percent": percent
        }
        return {"info": info, "plan": plan, 'status': 200}


    def put(self):
        args = self.parser.parse_args()
        week = args['week']
        month = args['month']
        year = args['year']
        args = self.parser.parse_args()
        if args['Authorization'] is None:
            return {'message': 'Unauthorized', 'status': 401}

        token = args['Authorization'].split(' ')[1]
        if User.verify_auth_token(token) is None:
            return {'message': 'Unauthorized', 'status': 401}
        user_id = User.verify_auth_token(token)['user_id']
        user = User.query.get(user_id)
        if user is None:
            return _BAD_REQUEST
        else:
            update_status = Stats.query.filter_by(user_id=user.id).first()
            if week and week.isdigit():
                update_status.week = week
            if month and month.isdigit():
                update_status.month = month
            if year and year.isdigit():
                update_status.year = year
            try:
                session.commit()
            except SQLAlchemyError:
                session.rollback()
            return _GOOD_REQUEST


api.add_resource(Statistics, '/stats')


class LogOut(Resource):
    def __init__(self):
        self.parser = reqparse.RequestParser()
        self.parser.add_argument('Authorization', location='headers')

    def post(self):
        args = self.parser.parse_args()
        if args['Authorization'] is None:
            return {'message': 'Unauthorized', 'status': 401}

        token = args['Authorization'].split(' ')[1]
        new = Tokens.query.filter_by(token=token).first()
        if new is not None:
            session.delete(new)
            try:
                session.commit()
            except SQLAlchemyError:
                session.rollback()

            return {'message': 'User logged out', 'status': 200}
        else:
            return _BAD_REQUEST


api.add_resource(LogOut, '/logout')


class DoneBooks(Resource):
    def __init__(self):
        self.parser = reqparse.RequestParser()
        self.parser.add_argument('Authorization', location='headers')

    def get(self):
        args = self.parser.parse_args()
        if args['Authorization'] is None:
            return {'message': 'Unauthorized', 'status': 401}
        token = args['Authorization'].split(' ')[1]
        if User.verify_auth_token(token) is None:
            return {'message': 'Unauthorized', 'status': 401}
        user_id = User.verify_auth_token(token)['user_id']
        user = User.query.get(user_id)
        if user is None:
            return _BAD_REQUEST
        else:
            done_book = UsersBooks.query.filter_by(user_id=user.id).filter_by(list='DN').all()
            count = len(done_book)
            info = []
            for book in done_book:
                book_id = book.books_id
                current_book = Books.query.get(book_id)
                info_book = {
                    "id": current_book.id,
                    "title": current_book.title,
                    "author": current_book.author,
                    "genre": current_book.genre,
                    "rate": book.rate,
                }
                info.append(info_book)
        return {'count': count, 'info': info, 'status': 200}


api.add_resource(DoneBooks, '/books/read')


class ProgressBooks(Resource):
    def __init__(self):
        self.parser = reqparse.RequestParser()
        self.parser.add_argument('Authorization', location='headers')

    def get(self):
        args = self.parser.parse_args()
        if args['Authorization'] is None:
            return {'message': 'Unauthorized', 'status': 401}
        token = args['Authorization'].split(' ')[1]
        if User.verify_auth_token(token) is None:
            return {'message': 'Unauthorized', 'status': 401}
        user_id = User.verify_auth_token(token)['user_id']
        user = User.query.get(user_id)
        if user is None:
            return _BAD_REQUEST
        else:
            info = []
            progress_book = UsersBooks.query.filter_by(user_id=user.id).filter_by(list='IP').all()
            count = len(progress_book)
            for book in progress_book:
                book_id = book.books_id
                current_book = Books.query.get(book_id)
                info_book = {
                    "id": current_book.id,
                    "title": current_book.title,
                    "author": current_book.author,
                    "genre": current_book.genre,
                    "rate": book.rate,

                }
                info.append(info_book)
        return {'count': count, 'info': info, 'status': 200}


api.add_resource(ProgressBooks, '/books/progress')


class FutureBooks(Resource):
    def __init__(self):
        self.parser = reqparse.RequestParser()
        self.parser.add_argument('Authorization', location='headers')

    def get(self):
        args = self.parser.parse_args()
        if args['Authorization'] is None:
            return {'message': 'Unauthorized', 'status': 401}
        token = args['Authorization'].split(' ')[1]
        if User.verify_auth_token(token) is None:
            return {'message': 'Unauthorized', 'status': 401}
        user_id = User.verify_auth_token(token)['user_id']
        user = User.query.get(user_id)
        if user is None:
            return _BAD_REQUEST
        else:
            future_book = UsersBooks.query.filter_by(user_id=user.id).filter_by(list='WR').all()
            count = len(future_book)
            info = []
            for book in future_book:
                book_id = book.books_id
                current_book = Books.query.get(book_id)
                info_book = {
                    "id": current_book.id,
                    "title": current_book.title,
                    "author": current_book.author,
                    "genre": current_book.genre,
                    "rate": book.rate,
                }
                info.append(info_book)
        return {'count': count, 'info': info, 'status': 200}


api.add_resource(FutureBooks, '/books/future')


class AddReviews(Resource):
    def __init__(self):
        self.parser = reqparse.RequestParser()
        self.parser.add_argument('text')
        self.parser.add_argument('Authorization', location='headers')

    def get(self, books_id):
        args = self.parser.parse_args()
        if args['Authorization'] is None:
            return {'message': 'Unauthorized', 'status': 401}
        token = args['Authorization'].split(' ')[1]
        if User.verify_auth_token(token) is None:
            return {'message': 'Unauthorized', 'status': 401}
        user_id = User.verify_auth_token(token)['user_id']
        user = User.query.get(user_id)
        exist_user = Reviews.query.filter_by(user_id=user_id).filter_by(
            books_id=books_id).first()
        if exist_user is None:
            can_write = True
        else:
            can_write = False
        list_reviews = Reviews.query.filter_by(books_id=books_id).all()
        count = len(list_reviews)
        info = []
        if count != 0:
            for review in list_reviews:
                user_id = review.user_id
                user = User.query.get(user_id)
                info_review = {
                    "username": user.username,
                    "text": review.text,
                    'created': review.data_added.strftime(format='%d/%m/%Y'),
                }
                info.append(info_review)
            return {'count': count, 'info': info, 'can_write': can_write, 'status': 200}
        else:
            return {'message': 'No reviews about this book', 'status': 200}

    def post(self, books_id):
        args = self.parser.parse_args()
        if args['Authorization'] is None:
            return {'message': 'Unauthorized', 'status': 401}
        token = args['Authorization'].split(' ')[1]
        if User.verify_auth_token(token) is None:
            return {'message': 'Unauthorized', 'status': 401}
        user_id = User.verify_auth_token(token)['user_id']
        user = User.query.get(user_id)
        text = args['text']
        exist_user = Reviews.query.filter_by(user_id=user_id).filter_by(books_id=books_id).first()
        if exist_user is not None:
            return {'status': 400,
                    'message': f'User {user.username} already left review on this book'}
        elif text is not None:
            review = Reviews(
                user_id=user.id,
                books_id=books_id,
                text=text
            )
            session.add(review)
            try:
                session.commit()
            except SQLAlchemyError:
                session.rollback()
            return {'message': 'Successfully created', 'status': 201}
        else:
            return _BAD_REQUEST


api.add_resource(AddReviews, '/books/<int:books_id>/reviews')


class HomepageTop(Resource):

    def __init__(self):
        self.parser = reqparse.RequestParser()
        self.parser.add_argument('Authorization', location='headers')

    def get(self):
        books = Books.query.order_by(desc('rate')).limit(20).all()
        list_books = []
        for book in books:
            info = {
                'id': book.id,
                'title': book.title,
                'author': book.author,
                'genre': book.genre,
                'rate': book.rate}

            list_books.append(info)

        return {'books': list_books, 'status': 200}


api.add_resource(HomepageTop, '/home/top')


class HomepageRec(Resource):
    def __init__(self):
        self.parser = reqparse.RequestParser()
        self.parser.add_argument('Authorization', location='headers')

    def get(self):
        args = self.parser.parse_args()
        if args['Authorization'] is None:
            return {'message': 'Unauthorized', 'status': 401}
        token = args['Authorization'].split(' ')[1]
        if User.verify_auth_token(token) is None:
            return {'message': 'Unauthorized', 'status': 401}
        user_id = User.verify_auth_token(token)['user_id']
        user = User.query.get(user_id)
        range_books = []
        books = UsersBooks.query.filter_by(user_id=user.id).all()
        print(len(books))
        if len(books) > 0:
            for book in books:
                range_books.append(book.books_id)

            fav_author = Books.query.with_entities(Books.author,
                                                   func.count(Books.author)). \
                group_by(Books.author). \
                filter(Books.id.in_(range_books)). \
                order_by(desc(func.count(Books.author))). \
                first()[0]
            fav_genre = Books.query.with_entities(Books.genre,
                                                  func.count(Books.genre)). \
                group_by(Books.genre). \
                filter(Books.id.in_(range_books)).order_by(
                desc(func.count(Books.genre))). \
                first()[0]

            recs = Books.query.filter(or_(Books.author == fav_author, Books.genre == fav_genre)). \
                filter(Books.id.notin_(range_books)). \
                order_by(desc('rate')). \
                limit(20).all()
            recommendations = []

            for rec in recs:
                info = {
                    'id': rec.id,
                    'title': rec.title,
                    'author': rec.author,
                    'genre': rec.genre,
                    'rate': rec.rate}
                recommendations.append(info)

            return {'books': recommendations, 'status': 200}
        else:
            return {'message': 'No recommendations yet.', 'status': 200}


api.add_resource(HomepageRec, '/home/rec')


class GoogleLogin(Resource):

    def __init__(self):
        self.parser = reqparse.RequestParser()
        self.parser.add_argument('email', required=True)

    def post(self):
        args = self.parser.parse_args()
        email = args['email']

        user = User.query.filter_by(email=email).first()
        if user is None:
            return {'status': 404,
                    'message': f'User with email {email} does not exist'}
        else:
            check_login = Tokens.query.filter_by(user_id=user.id).first()
            if check_login is None:
                token = user.generate_auth_token(expiration=10000)
                tkn = str(token)
                new = Tokens(token=tkn[2:len(tkn) - 1], user_id=user.id)
                session.add(new)
                try:
                    session.commit()
                except SQLAlchemyError:
                    session.rollback()
                return _GOOD_REQUEST, {'Bearer': token}
            else:
                return {'message': 'User already logged in',
                        'status': '400'}


api.add_resource(GoogleLogin, '/google/login')


class GoogleRegister(Resource):

    def __init__(self):
        self.parser = reqparse.RequestParser()
        self.parser.add_argument('email', required=True)
        self.parser.add_argument('password', required=True)

    def post(self):
        args = self.parser.parse_args()
        email = args['email']
        password = args['password']
        username = email[0:email.find('@')]
        user = User.query.filter_by(email=email).first()
        if user is not None:
            return {'status': 400,
                    'message': f'User with email {email} already exists'}
        user = User(
            email=email,
            username=username)
        user.set_password(password)
        with Image.open('bookspace/static/images/avatar.png') as img:
            output = io.BytesIO()
            img.save(output, format='png')
            image_data = output.getvalue()
            user.image = image_data
        session.add(user)
        try:
            session.commit()
        except SQLAlchemyError:
            session.rollback()
        status = Stats(
            user_id=user.id)
        session.add(user)
        session.add(status)
        try:
            session.commit()
        except SQLAlchemyError:
            session.rollback()

        msg = Message(f"BookSpace register",
                      recipients=[email])
        msg.body = f"You've been registered! To login, use this password (you have to change it later): {password}"
        mail.send(msg)
        return {'message': 'Successfully created', 'status': 201}


api.add_resource(GoogleRegister, '/google/register')


class RestorePass(Resource):

    @staticmethod
    def generate_password(stringlen=8):
        """Generate a random string of fixed length """
        letters = string.ascii_lowercase
        return ''.join(random.choice(letters) for i in range(stringlen))

    def __init__(self):
        self.parser = reqparse.RequestParser()
        self.parser.add_argument('email', required=True)

    def post(self):
        args = self.parser.parse_args()
        email = args['email']
        password = self.generate_password()
        user = User.query.filter_by(email=email).first()
        if user is not None:
            user.set_password(password)
            msg = Message(f"BookSpace password",
                          recipients=[email])
            msg.body = f"Your password was successfully changed. " \
                f"To login, use this password (you have to change it later): {password}"
            mail.send(msg)
            session.add(user)
            try:
                session.commit()
            except SQLAlchemyError:
                session.rollback()
            return _GOOD_REQUEST
        else:
            return _BAD_REQUEST


api.add_resource(RestorePass, '/login/restore')


class Search(Resource):
    def __init__(self):
        self.parser = reqparse.RequestParser()
        self.parser.add_argument('search')
        self.parser.add_argument('Authorization', location='headers')

    def post(self):
        args = self.parser.parse_args()
        search = args['search']
        if args['Authorization'] is None:
            return {'message': 'Unauthorized', 'status': 401}
        token = args['Authorization'].split(' ')[1]
        if User.verify_auth_token(token) is None:
            return {'message': 'Unauthorized', 'status': 401}
        user_id = User.verify_auth_token(token)['user_id']
        user = User.query.get(user_id)
        if user is None:
            return _BAD_REQUEST
        elif search is not None:
            info = []
            research = search.strip()
            query = f'%{research}%'
            print(research)
            result = Books.query.filter(or_(Books.genre.ilike(query), Books.title.ilike(query), Books.author.ilike(query))).all()
            print(result)

            for book in result:
                listbook = {
                    "id": book.id,
                    "title": book.title,
                    "author": book.author,
                    "genre": book.genre
                }
                info.append(listbook)
            return {'count': len(info), 'books': info, 'status': 200}
        return _BAD_REQUEST


api.add_resource(Search, '/books/search')


class IndexPage(Resource):
    def __init__(self):
        pass

    def get(self):
        return make_response(render_template('index.html'), 200)

    def post(self):
        try:
            return send_file('static/files/app-debug.apk',
                             as_attachment=True,
                             attachment_filename='app.apk')
        except Exception as e:
            return str(e)


api.add_resource(IndexPage, '/index')


class RecentBooks(Resource):
    def __init__(self):
        self.parser = reqparse.RequestParser()
        self.parser.add_argument('Authorization', location='headers')

    def get(self):
        args = self.parser.parse_args()
        auth = args.get('Authorization')
        if not auth:
            return {'message': 'Unauthorized', 'status': 401}
        token = auth.split(' ')[1]
        if not User.verify_auth_token(token):
            return {'message': 'Unauthorized', 'status': 401}
        user_id = User.verify_auth_token(token)['user_id']
        user = User.query.get(user_id)
        if not user:
            return _BAD_REQUEST
        user_books = UsersBooks.query.filter_by(user_id=user.id).order_by(desc(UsersBooks.data_added)).limit(3).all()
        books = []
        for book in user_books:
            book_data = Books.query.filter_by(id=book.books_id).first()
            info = {
                'id': book.id,
                'list': book.list.value,
                'title': book_data.title,
                'author': book_data.author,
                'rate': book.rate
            }
            books.append(info)
        return {'books': books, 'status': 200}


api.add_resource(RecentBooks, '/books/recent')
