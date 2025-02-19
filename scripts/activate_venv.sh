#!/bin/bash
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
else
    echo "Virtual environment not found!"
    exit 1
fi
