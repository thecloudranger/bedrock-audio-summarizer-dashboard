import streamlit as st
import boto3
import sounddevice as sd
import numpy as np
import wave
import tempfile
import os
from datetime import datetime
import uuid
from botocore.exceptions import ClientError

def init_aws_client():
    """Initialize AWS S3 client"""
    return boto3.client('s3')

def get_s3_presigned_url(bucket, key, expiration=3600):
    """Generate a presigned URL for the S3 object"""
    s3_client = init_aws_client()
    try:
        response = s3_client.generate_presigned_url('get_object',
                                                  Params={'Bucket': bucket,
                                                         'Key': key},
                                                  ExpiresIn=expiration)
    except ClientError as e:
        st.error(f"Error generating presigned URL: {e}")
        return None
    return response

def list_s3_files(bucket, prefix, file_extension=None):
    """List files in S3 bucket with given prefix and optional file extension filter"""
    s3_client = init_aws_client()
    try:
        response = s3_client.list_objects_v2(Bucket=bucket, Prefix=prefix)
        if 'Contents' in response:
            files = [item['Key'] for item in response['Contents']]
            if file_extension:
                files = [f for f in files if f.lower().endswith(file_extension.lower())]
            return files
        return []
    except ClientError as e:
        st.error(f"Error listing S3 files: {e}")
        return []

def read_text_file(bucket, key):
    """Read text file content from S3"""
    s3_client = init_aws_client()
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        content = response['Body'].read().decode('utf-8')
        return content
    except ClientError as e:
        st.error(f"Error reading file: {e}")
        return None

def record_audio(duration, sample_rate=44100):
    """Record audio using sounddevice and save as WAV"""
    try:
        # Record audio
        recording = sd.rec(int(duration * sample_rate),
                         samplerate=sample_rate,
                         channels=1,  # Mono recording for simplicity
                         dtype=np.int16)
        st.info("Recording in progress... Please speak into your microphone.")
        sd.wait()
        st.success("Recording completed!")
        return recording, sample_rate
    except Exception as e:
        st.error(f"Error recording audio: {e}")
        return None, None

def save_wav_file(recording, sample_rate):
    """Save the recorded audio as a WAV file"""
    try:
        # Create temporary WAV file
        temp_wav = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')

        with wave.open(temp_wav.name, 'wb') as wf:
            wf.setnchannels(1)  # Mono
            wf.setsampwidth(2)  # 2 bytes for int16
            wf.setframerate(sample_rate)
            wf.writeframes(recording.tobytes())

        return temp_wav.name
    except Exception as e:
        st.error(f"Error saving WAV file: {e}")
        return None

def generate_unique_filename(original_filename):
    """Generate a unique filename using timestamp and UUID"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_id = str(uuid.uuid4())[:8]  # Using first 8 characters of UUID
    name, ext = os.path.splitext(original_filename)
    return f"{name}_{timestamp}_{unique_id}{ext}"

def check_file_exists(s3_client, bucket, key):
    """Check if a file already exists in S3"""
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        if e.response['Error']['Code'] == '404':
            return False
        raise

def upload_to_s3(bucket, file_path, original_filename):
    """Upload file to S3 with a unique filename"""
    s3_client = init_aws_client()
    try:
        # Generate unique filename
        unique_filename = generate_unique_filename(original_filename)
        key = f"source/{unique_filename}"

        # Double check if file exists (although unlikely with our naming scheme)
        while check_file_exists(s3_client, bucket, key):
            unique_filename = generate_unique_filename(original_filename)
            key = f"source/{unique_filename}"

        # Upload file
        s3_client.upload_file(file_path, bucket, key)
        return True, unique_filename
    except ClientError as e:
        st.error(f"Error uploading to S3: {e}")
        return False, None

def main():
    # Set page config with dark theme
    st.set_page_config(
        page_title="Audio Summarizer Dashboard",
        page_icon="🎙️",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    # Move bucket selection to sidebar
    with st.sidebar:
        st.title("🔧 Configuration")
        bucket_name = st.text_input(
            "S3 Bucket Name",
            placeholder="my-audio-bucket",
            help="Enter the name of your S3 bucket where files will be stored"
        )

        if st.button("🔄 Refresh Files", use_container_width=True):
            st.session_state['refresh_timestamp'] = datetime.now()

        st.markdown("---")

        # Move recording controls to sidebar
        st.subheader("🎙️ New Recording")
        duration = st.slider(
            "Duration (seconds)",
            min_value=1,
            max_value=300,
            value=60,
            help="Choose recording duration"
        )

        if st.button("🔴 Start Recording", use_container_width=True):
            recording, sample_rate = record_audio(duration)

            if recording is not None:
                temp_wav = save_wav_file(recording, sample_rate)

                if temp_wav:
                    try:
                        success, filename = upload_to_s3(bucket_name, temp_wav, "recording.wav")

                        if success:
                            st.success(f"✅ Recording saved as {filename}")
                            st.audio(temp_wav)
                        else:
                            st.error("❌ Upload failed")
                    finally:
                        if temp_wav and os.path.exists(temp_wav):
                            os.unlink(temp_wav)

    # Main content area
    if bucket_name:
        # Tabs for different sections
        tab1, tab2 = st.tabs(["📚 Library", "📝 Content Viewer"])

        with tab1:
            # Files section with improved layout
            files_col1, files_col2, files_col3 = st.columns(3)

            with files_col1:
                st.subheader("🎵 Audio Files")
                audio_container = st.container()
                with audio_container:
                    audio_files = list_s3_files(bucket_name, "source/")
                    if not audio_files or (len(audio_files) == 1 and audio_files[0] == "source/"):
                        st.info("No audio files available")
                    else:
                        for audio_file in audio_files:
                            if audio_file != "source/":
                                col_play, col_info = st.columns([1, 3])
                                with col_play:
                                    if st.button("▶️", key=f"play_{audio_file}"):
                                        url = get_s3_presigned_url(bucket_name, audio_file)
                                        if url:
                                            st.session_state['current_audio'] = {
                                                'url': url,
                                                'filename': os.path.basename(audio_file)
                                            }
                                with col_info:
                                    st.write(os.path.basename(audio_file))
                                    if 'current_audio' in st.session_state and \
                                       st.session_state['current_audio']['filename'] == os.path.basename(audio_file):
                                        st.audio(st.session_state['current_audio']['url'])

            with files_col2:
                st.subheader("📄 Transcripts")
                trans_container = st.container()
                with trans_container:
                    transcription_files = list_s3_files(bucket_name, "transcription/", ".txt")
                    if not transcription_files:
                        st.info("No transcripts available")
                    else:
                        for trans_file in transcription_files:
                            if trans_file != "transcription/":
                                col_view, col_info = st.columns([1, 3])
                                with col_view:
                                    if st.button("👁️", key=f"view_{trans_file}"):
                                        content = read_text_file(bucket_name, trans_file)
                                        if content:
                                            st.session_state['current_transcription'] = {
                                                'filename': os.path.basename(trans_file),
                                                'content': content
                                            }
                                with col_info:
                                    st.write(os.path.basename(trans_file))

            with files_col3:
                st.subheader("📊 Summaries")
                summary_container = st.container()
                with summary_container:
                    summary_files = list_s3_files(bucket_name, "processed/")
                    if not summary_files or (len(summary_files) == 1 and summary_files[0] == "processed/"):
                        st.info("No summaries available")
                    else:
                        for summary_file in summary_files:
                            if summary_file != "processed/":
                                col_view, col_info = st.columns([1, 3])
                                with col_view:
                                    if st.button("👁️", key=f"view_{summary_file}"):
                                        content = read_text_file(bucket_name, summary_file)
                                        if content:
                                            st.session_state['current_summary'] = {
                                                'filename': os.path.basename(summary_file),
                                                'content': content
                                            }
                                with col_info:
                                    st.write(os.path.basename(summary_file))

        with tab2:
            # Content viewer with better organization
            if 'current_transcription' in st.session_state or 'current_summary' in st.session_state:
                viewer_col1, viewer_col2 = st.columns(2)

                with viewer_col1:
                    if 'current_transcription' in st.session_state:
                        st.subheader(f"📝 Transcript: {st.session_state['current_transcription']['filename']}")
                        st.text_area(
                            "",
                            st.session_state['current_transcription']['content'],
                            height=600
                        )

                with viewer_col2:
                    if 'current_summary' in st.session_state:
                        st.subheader(f"📊 Summary: {st.session_state['current_summary']['filename']}")
                        st.text_area(
                            "",
                            st.session_state['current_summary']['content'],
                            height=600
                        )
            else:
                st.info("Select a transcript or summary from the Library tab to view its content")

    else:
        # Welcome message when no bucket is selected
        st.info("👈 Please enter your S3 bucket name in the sidebar to get started")

    # Footer
    st.markdown("---")
    st.markdown("""
        <div style='text-align: center'>
            <p>Built with Streamlit • Amazon S3 • AWS Transcribe • Amazon Bedrock</p>
        </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
