from flask import Flask
from flask_cors import CORS

from features.feedback_report_generator.routes import bp as frg_bp
from features.register_feedback.routes import bp as rf_bp

def create_app():
    app = Flask(__name__, template_folder="templates")
    CORS(app)

    # blueprints
    app.register_blueprint(frg_bp)
    app.register_blueprint(rf_bp)

    return app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
