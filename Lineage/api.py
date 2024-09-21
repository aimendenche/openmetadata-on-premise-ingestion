from flask import Flask, redirect, url_for, session
import secrets

app = Flask(__name__)

# Generate a random 24-character secret key
app.secret_key = secrets.token_hex(24)


@app.route('/')
def hello_world():
    if 'authenticated' in session:
        return 'Hello, World!'
    else:
        return redirect(url_for('login'))


@app.route('/login')
def login():
    # Replace with your actual client_id and WSO2 IS host information
    wso2_authorize_url = (
        'https://localhost:9443/oauth2/authorize'
        '?response_type=code'
        '&client_id=test-wso2'  # Replace with your actual client_id
        '&redirect_uri=http://127.0.0.1:5000/callback'  # The URL to your Flask endpoint
        '&scope=openid'
    )
    return redirect(wso2_authorize_url)


@app.route('/callback')
def callback():
    # Handle the callback from WSO2 IS after authentication
    # This is where you can exchange the authorization code for an access token
    # and perform any necessary actions with the user's session.

    # For example, set the 'authenticated' session variable to indicate successful authentication
    session['authenticated'] = True

    return redirect(url_for('hello_world'))


@app.route('/logout')
def logout():
    session.pop('authenticated', None)
    return 'You have been logged out.'


if __name__ == '__main__':
    app.run(debug=True, port=5000)
