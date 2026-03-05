from flask import request, Response
from functools import wraps
from config import APP_USERNAME, APP_PASSWORD

def check_auth(username: str, password: str) -> bool:
    return username == APP_USERNAME and password == APP_PASSWORD

def authenticate():
    return Response(
        "Could not verify your access.\nYou need to login with proper credentials.",
        401,
        {"WWW-Authenticate": 'Basic realm="Login Required"'}
    )

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated
