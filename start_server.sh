#!/bin/bash

# Start the FastAPI server for prompt editor
# Access the editor at: http://localhost:8000/prompts/editor

echo "Starting Context Processor server..."
echo "Prompt Editor will be available at: http://localhost:8000/prompts/editor"
echo ""

uvicorn main:app --reload --host 0.0.0.0 --port 8000
