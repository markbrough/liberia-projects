from flask import Flask, render_template, session, request, current_app
from flask_login import current_user

from maediprojects import commands, views, extensions


def create_app(config_object='config'):
    """An application factory, as explained here: http://flask.pocoo.org/docs/patterns/appfactories/.

    :param config_object: The configuration object to use.
    """
    app = Flask(__name__.split('.')[0])
    app.config.from_object(config_object)
    register_extensions(app)
    register_commands(app)
    register_blueprints(app)
    register_errorhandlers(app)
    register_hooks(app)
    return app


def register_commands(app):
    """Register Click commands."""
    app.cli.add_command(commands.setup)
    app.cli.add_command(commands.setup_country)
    app.cli.add_command(commands.import_liberia)
    app.cli.add_command(commands.import_psip)
    app.cli.add_command(commands.import_currencies_from_file)
    app.cli.add_command(commands.import_currencies_from_url)
    app.cli.add_command(commands.delete_currencies)
    app.cli.add_command(commands.test_closest_date)
    app.cli.add_command(commands.import_iati)
    app.cli.add_command(commands.import_psip_transactions)
    app.cli.add_command(commands.add_user_role)
    app.cli.add_command(commands.delete_user_role)
    app.cli.add_command(commands.list_user_roles)
    app.cli.add_command(commands.list_users)
    app.cli.add_command(commands.list_roles)


def check_enforce_sqlite_fkey_constraints(app):
    if app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite"):
        with app.app_context():
            def _fk_pragma_on_connect(dbapi_con, con_record):
                dbapi_con.execute('pragma foreign_keys=ON')

            from sqlalchemy import event
            event.listen(extensions.db.engine, 'connect', _fk_pragma_on_connect)


def register_extensions(app):
    extensions.db.init_app(app)
    check_enforce_sqlite_fkey_constraints(app)
    extensions.migrate.init_app(app, extensions.db)
    extensions.babel.init_app(app)
    extensions.mail.init_app(app)
    extensions.login_manager.init_app(app)


def register_blueprints(app):
    app.register_blueprint(views.activities.blueprint)
    app.register_blueprint(views.api.blueprint)
    app.register_blueprint(views.codelists.blueprint)
    app.register_blueprint(views.documentation.blueprint)
    app.register_blueprint(views.users.blueprint)
    app.register_blueprint(views.reports.blueprint)
    app.register_blueprint(views.exports.blueprint)
    app.register_blueprint(views.management.blueprint)


def register_errorhandlers(app):
    def render_error(error):
        error_code = getattr(error, 'code', 500)
        return render_template('{0}.html'.format(error_code),
                               loggedinuser=current_user), error_code
    for errcode in [404, 500]:
        app.errorhandler(errcode)(render_error)
    return None


def register_hooks(app):
    @app.before_request
    def setup_default_permissions():
        if current_user.is_authenticated:
            assert models.User.query.get(current_user.id)
            session["permissions"] = current_user.permissions_dict
        else:
            session["permissions"] = {}
            current_user.permissions_dict = {
                'domestic_external': 'none',
                'domestic_external_edit': 'none'
            }
            if request.headers['Host'] == "psip.liberiaprojects.org":
                session["permissions"]["domestic_external"] = "domestic"
            elif request.headers['Host'] == "liberiaprojects.org":
                session["permissions"]["domestic_external"] = "external"
            # Only used for bug testing locally
            elif request.headers['Host'] == "127.0.0.1:5000":
                session["permissions"]["domestic_external"] = "domestic"
            else:
                session["permissions"]["domestic_external"] = "both"
