# app.py

from flask import Flask, request, jsonify
from supabase import create_client, Client
import os
import librosa
import soundfile as sf
from basic_pitch.inference import predict_and_save_midi
import numpy as np

app = Flask(__name__)

# Initialize Supabase client
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Helper function to map musical keys to semitone shifts (simplified)
def get_semitone_shift(current_key, target_key):
    # This is a very simplified mapping. A real app would need a more robust music theory library.
    # For example, mapping C=0, C#=1, D=2, etc.
    key_map = {
        "C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5,
        "F#": 6, "Gb": 6, "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11
    }
    
    current_root = current_key.split(" ")[0] # e.g., "C" from "C Major"
    target_root = target_key.split(" ")[0]

    if current_root in key_map and target_root in key_map:
        return key_map[target_root] - key_map[current_root]
    return 0 # No shift if keys are not recognized

@app.route("/process-audio", methods=["POST"])
def process_audio():
    try:
        data = request.json
        audio_file_url = data.get("audio_file_url")
        user_id = data.get("user_id")
        audio_file_id = data.get("audio_file_id")
        desired_key = data.get("desired_key")
        desired_tempo = data.get("desired_tempo")

        # Download audio file from Supabase Storage
        # Assuming audio_file_url is a direct URL to the file in Supabase Storage
        # You might need to implement proper authentication/authorization here
        response = requests.get(audio_file_url)
        if response.status_code != 200:
            return jsonify({"error": "Failed to download audio file"}), 400

        local_audio_path = f"./temp_{audio_file_id}.wav"
        with open(local_audio_path, "wb") as f:
            f.write(response.content)

        # Load audio
        y, sr = librosa.load(local_audio_path)

        # 1. Key and Tempo Detection (using librosa)
        # This is a placeholder, librosa.key_extract and librosa.tempo are more complex
        # and usually involve more context and algorithms.
        estimated_tempo = librosa.beat.tempo(y=y, sr=sr)[0]
        # For key detection, a more robust approach is needed, this is a simplification
        # Example: Using a pre-trained model or more advanced harmonic analysis
        # For now, let\'s assume a placeholder or a simple harmonic analysis result
        estimated_key = "C Major" # Placeholder

        # 2. Pitch and Tempo Modification
        y_modified = y
        sr_modified = sr

        if desired_tempo and desired_tempo != estimated_tempo:
            speed_ratio = float(desired_tempo) / estimated_tempo
            y_modified = librosa.effects.time_stretch(y_modified, rate=speed_ratio)

        if desired_key and desired_key != estimated_key:
            semitone_shift = get_semitone_shift(estimated_key, desired_key)
            y_modified = librosa.effects.pitch_shift(y_modified, sr=sr_modified, n_steps=semitone_shift)

        # Save modified audio
        modified_audio_path = f"./modified_{audio_file_id}.wav"
        sf.write(modified_audio_path, y_modified, sr_modified)

        # 3. MIDI Data Extraction (using Basic-Pitch)
        midi_output_path = f"./midi_{audio_file_id}.mid"
        predict_and_save_midi(audio_path_list=[local_audio_path], output_dir="./", pm_path=midi_output_path)

        # Upload processed files to Supabase Storage
        storage_path_modified_audio = f"{user_id}/processed_audio/modified_{audio_file_id}.wav"
        with open(modified_audio_path, "rb") as f:
            supabase.storage.from_("processed-audio").upload(storage_path_modified_audio, f.read(),file_options={'content-type': 'audio/wav'})

        storage_path_midi = f"{user_id}/processed_midi/midi_{audio_file_id}.mid"
        with open(midi_output_path, "rb") as f:
            supabase.storage.from_("processed-midi").upload(storage_path_midi, f.read(), file_options={"content-type": "audio/midi"})

        # Clean up temporary files
        os.remove(local_audio_path)
        os.remove(modified_audio_path)
        os.remove(midi_output_path)

        return jsonify({
            "message": "Audio processed successfully",
            "modified_audio_url": f"{SUPABASE_URL}/storage/v1/object/public/processed-audio/{storage_path_modified_audio}",
            "midi_url": f"{SUPABASE_URL}/storage/v1/object/public/processed-midi/{storage_path_midi}"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=os.environ.get("PORT", 5000))
