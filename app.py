from flask import Flask, render_template
import cheap_god_of_war  # import your code if it has functions

app = Flask(__name__)

@app.route('/')
def home():
    # You can call a function from your Python file or just display text
    return "Welcome to Cheap God of War demo!"

if __name__ == '__main__':
    app.run(debug=True)
