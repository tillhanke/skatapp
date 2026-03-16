#!/bin/bash

export FLASK_APP=app.py
.venv/bin/flask run --no-reload --host=0.0.0.0 --port=5001

