# app.py

import os
import uuid 
import json
import tempfile
from flask import Flask, request, jsonify
from flask_cors import CORS 
from supabase import create_client, Client 
from basic_pitch.inference import predict
# from librosa import load # Uncomment if you use librosa functions directly

# --- Configuration ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

# --- Initialize Supabase Client ---
# Ensure SUPABASE_URL and SUPABASE_KEY are set as environment variables
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) 

# --- Initialize Flask App ---
app = Flask(__name__)

# --- CORS Configuration ---
# IMPORTANT: This allows your frontend to send requests to this backend.
# Added your specific IP address (http://192.168.38.101:8000) 
# and your domain (https://www.rork.com)
CORS(app, origins=[
    "https://www.rork.com", 
    "http://192.168.38.101:8000",
    "http://192.168.38.101",
    "http://localhost:3000" # Common local development environment
    "https://duke-unshaking-alternatively.ngrok-free.dev"
]) 

# --- Core Processing Function ---
def run_basic_pitch_processing(audio_path):
    """Processes audio file using basic-pitch."""
    
    # Run the model inference
    model_output, _, _ = predict(audio_path)
    
    # You need to decide how to serialize the model_output (note events) to JSON.
    # For now, returning a simple placeholder:
    return "MIDI data generated successfully" 

# --- API Routes ---

# Basic health check route
@app.route('/', methods=['GET'])
def index():
    return "Audio Backend is running!", 200

# File processing route
@app.route('/api/process-audio', methods=['POST'])
def process_audio():
    # 1. Input Check
    if 'audio_file' not in request.files:
        return jsonify({"error": "Missing audio file in request"}), 400
    file = request.files['audio_file']
    
    # 2. Setup paths and save file temporarily
    unique_filename = f"{uuid.uuid4()}_{file.filename}"
    
    # Use tempfile module for safer temporary file handling
    with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{file.filename}") as tmp:
        file.save(tmp.name)
        temp_path = tmp.name
    
    storage_path = f'user_audio/{unique_filename}'
    bucket_name = 'audio-uploads'
    
    try:
        # 3. Process Audio
        midi_result = run_basic_pitch_processing(temp_path) 

        # 4. Supabase Storage Upload
        upload_response = supabase.storage.from_(bucket_name).upload(
            file=temp_path,
            path=storage_path
        )
        
        # 5. Supabase Database Insertion (Metadata)
        supabase.table('audio_metadata').insert({
            "filename": file.filename,
            "storage_url": storage_path,
            "processed_data": midi_result,
            "status": "completed"
        }).execute()
        
        # 6. Response
        return jsonify({"message": "Audio processed and saved.", "data": midi_result, "storage_path": storage_path}), 200

    except Exception as e:
        # Crucial for debugging errors!
        print(f"Error during processing: {e}") 
        return jsonify({"error": "Server error during processing.", "details": str(e)}), 500

    finally:
        # 7. Cleanup (Ensures the temp file is deleted regardless of success/failure)
        if os.path.exists(temp_path):
            os.remove(temp_path)


if __name__ == '__main__':
    # This block is for local testing only
    app.run(debug=True)
