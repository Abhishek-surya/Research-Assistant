import flask
from firebase_functions import https_fn
from fastapi import FastAPI
from a2wsgi import ASGIMiddleware
from werkzeug.test import run_wsgi_app

app = FastAPI()

@app.get("/hello")
def hello():
    return {"message": "hello"}

wsgi_app = ASGIMiddleware(app)

@https_fn.on_request()
def api(req: https_fn.Request) -> https_fn.Response:
    app_iter, status, headers = run_wsgi_app(wsgi_app, req.environ)
    return flask.Response(app_iter, status=status, headers=list(headers))

print("Syntax and imports successful!")
