from flask import Flask, render_template, request, jsonify
from datetime import datetime
import pytz
import re
import html as html_mod
import requests
import base64
import io
from PIL import Image

app = Flask(__name__)

# 🔐 API Keys
ELEVENLABS_API_KEY = "e68f0494c2c0e5995be196896af2418e574d1b00d96e4b1409bd28084865a64c"
ELEVENLABS_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"
GROQ_API_KEY = "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"  # <-- YAHAN APNI GROQ API KEY DAALO

# ====== GROQ API CONFIG (Cloud-based Llama 4) ======
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
CHAT_MODEL = "openai/gpt-oss-120b"         # Llama 4 Scout for chat
VISION_MODEL = "qwen/qwen3.6-27b"        # Llama 4 Scout = multimodal (text + image)


def groq_chat(messages, model=CHAT_MODEL):
    """Send chat messages to Groq API (OpenAI-compatible)."""
    url = f"{GROQ_BASE_URL}/chat/completions"
    
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": 300,        # ⚡ Short responses = fast
        "temperature": 0.7
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            return data['choices'][0]['message']['content']
        else:
            print(f"Groq error: {response.status_code} - {response.text}")
            return None
    except requests.exceptions.Timeout:
        print("Groq timeout!")
        return None
    except Exception as e:
        print(f"Groq connection error: {e}")
        return None


def groq_vision(image_bytes, prompt):
    """Send image + prompt to Groq API (Llama 4 supports images natively)."""
    # Convert image to base64 for API
    img_base64 = base64.b64encode(image_bytes).decode('utf-8')
    
    url = f"{GROQ_BASE_URL}/chat/completions"
    
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    # Short prompt for speed
    short_prompt = prompt[:500] if len(prompt) > 500 else prompt
    
    payload = {
        "model": VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": short_prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{img_base64}"
                        }
                    }
                ]
            }
        ],
        "max_tokens": 200,         # ⚡ Short response = fast
        "temperature": 0.5
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=20)
        if response.status_code == 200:
            data = response.json()
            return data['choices'][0]['message']['content']
        else:
            print(f"Groq Vision error: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"Groq Vision connection error: {e}")
        return None


def clean_markdown(text):
    """Clean ALL markdown formatting - bold, italic, bullets, headings, code blocks"""
    if not text:
        return text
    
    # ====== STEP 1: Extract & protect code blocks ======
    code_blocks = []
    def save_code(match):
        lang = match.group(1) or ''
        code = match.group(2)
        escaped = html_mod.escape(code)
        code_blocks.append(f'<pre><code class="lang-{lang}">{escaped}</code></pre>')
        return f'%%CB_{len(code_blocks)-1}%%'
    text = re.sub(r'```(\w*)\n(.*?)```', save_code, text, flags=re.DOTALL)
    
    # ====== STEP 2: Extract inline code ======
    inline_codes = []
    def save_inline(match):
        c = match.group(1)
        inline_codes.append(f'<code>{html_mod.escape(c)}</code>')
        return f'%%IC_{len(inline_codes)-1}%%'
    text = re.sub(r'`([^`]+)`', save_inline, text)
    
    # ====== STEP 3: Remove ALL bold/italic markers ======
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'\1', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    
    # ====== STEP 4: Process line by line ======
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        if re.match(r'^\s*\*\s+', line):
            line = re.sub(r'^(\s*)\*\s+', r'\1• ', line)
        elif re.match(r'^\s*-\s+', line):
            line = re.sub(r'^(\s*)- ', r'\1→ ', line)
        else:
            line = re.sub(r'\*([^*]+)\*', r'\1', line)
        
        line = line.replace('*', '')
        line = re.sub(r'^#+\s+', '', line)
        if re.match(r'^\s*[-*_]{3,}\s*$', line.strip()):
            continue
        line = re.sub(r'^\s*>\s+', '', line)
        line = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', line)
        
        cleaned_lines.append(line)
    
    text = '\n'.join(cleaned_lines)
    text = re.sub(r'\n{4,}', '\n\n\n', text)
    
    parts = re.split(r'(%%CB_\d+%%)', text)
    for i in range(len(parts)):
        if not re.match(r'%%CB_\d+%%', parts[i]):
            parts[i] = parts[i].replace('\n\n', '</p><p>')
            parts[i] = parts[i].replace('\n', '<br>')
    text = ''.join(parts)
    
    if not text.startswith('<'):
        text = f'<p>{text}</p>'
    
    for i, block in enumerate(code_blocks):
        text = text.replace(f'%%CB_{i}%%', block)
    for i, block in enumerate(inline_codes):
        text = text.replace(f'%%IC_{i}%%', block)
    
    text = re.sub(r'<p>\s*<br>\s*', '<p>', text)
    text = re.sub(r'\s*<br>\s*</p>', '</p>', text)
    text = re.sub(r'<br><br>', '<br>', text)
    
    return text.strip()


def text_to_speech(text):
    """Convert text to speech using ElevenLabs API and return base64 audio."""
    clean_text = re.sub(r'<[^>]+>', '', text)
    clean_text = clean_text.replace('•', 'bullet point')
    clean_text = clean_text.replace('→', 'to')
    
    if len(clean_text) > 500:
        clean_text = clean_text[:500] + "..."
    
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
    
    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": ELEVENLABS_API_KEY
    }
    
    data = {
        "text": clean_text,
        "model_id": "eleven_monolingual_v1",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.5
        }
    }
    
    try:
        response = requests.post(url, json=data, headers=headers)
        if response.status_code == 200:
            audio_base64 = base64.b64encode(response.content).decode('utf-8')
            return audio_base64
        else:
            print(f"ElevenLabs error: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"TTS error: {e}")
        return None


# ====== Conversation History ======
conversation_history = []
MAX_PAIRS = 10
MAX_ENTRIES = MAX_PAIRS * 2

SYSTEM_PROMPT = {
    "role": "system",
    "content": (
        "You are GEN AI, a helpful, precise, and intelligent assistant. "
        "You respond in a thoughtful, clear manner. "
        "You provide detailed, accurate information and help with any task. "
        "Keep your responses well-structured but conversational. "
        "Be concise and respond in 2-3 paragraphs maximum."
    )
}


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/chat', methods=['POST'])
def chat():
    global conversation_history
    
    data = request.get_json()
    user_message = data.get('message', '').strip()
    
    if not user_message:
        return jsonify({'reply': 'Please enter a message.'}), 400
    
    try:
        ist = pytz.timezone('Asia/Kolkata')
        current_date = datetime.now(ist).strftime("%A, %d %B %Y at %I:%M %p")
        
        messages = [SYSTEM_PROMPT]
        messages.append({
            "role": "system",
            "content": f"Current Date & Time: {current_date}"
        })
        messages.extend(conversation_history)
        messages.append({"role": "user", "content": user_message})
        
        bot_reply = groq_chat(messages)
        
        if not bot_reply:
            return jsonify({'reply': '⚠️ Groq API is not responding. Check your API key and internet connection!'}), 500
        
        display_reply = clean_markdown(bot_reply)
        
        conversation_history.append({"role": "user", "content": user_message})
        conversation_history.append({"role": "assistant", "content": bot_reply})
        
        if len(conversation_history) > MAX_ENTRIES:
            conversation_history = conversation_history[-MAX_ENTRIES:]
        
        return jsonify({'reply': display_reply})
    
    except Exception as e:
        return jsonify({'reply': f'Sorry, I encountered an error: {str(e)}'}), 500


@app.route('/voice', methods=['POST'])
def voice_chat():
    """Handle voice input - get AI response AND return audio."""
    global conversation_history
    
    data = request.get_json()
    user_message = data.get('message', '').strip()
    
    if not user_message:
        return jsonify({'reply': 'Please speak something.'}), 400
    
    try:
        ist = pytz.timezone('Asia/Kolkata')
        current_date = datetime.now(ist).strftime("%A, %d %B %Y at %I:%M %p")
        
        messages = [SYSTEM_PROMPT]
        messages.append({
            "role": "system",
            "content": f"Current Date & Time: {current_date}"
        })
        messages.extend(conversation_history)
        messages.append({"role": "user", "content": user_message})
        
        bot_reply = groq_chat(messages)
        
        if not bot_reply:
            return jsonify({'reply': '⚠️ Groq API is not responding.', 'audio': None}), 500
        
        display_reply = clean_markdown(bot_reply)
        
        plain_reply = re.sub(r'<[^>]+>', '', bot_reply)
        plain_reply = plain_reply.replace('*', '').replace('#', '').strip()
        
        audio_base64 = text_to_speech(plain_reply)
        
        conversation_history.append({"role": "user", "content": user_message})
        conversation_history.append({"role": "assistant", "content": bot_reply})
        
        if len(conversation_history) > MAX_ENTRIES:
            conversation_history = conversation_history[-MAX_ENTRIES:]
        
        return jsonify({
            'reply': display_reply,
            'audio': audio_base64
        })
    
    except Exception as e:
        return jsonify({'reply': f'Sorry, I encountered an error: {str(e)}', 'audio': None}), 500


@app.route('/reset', methods=['POST'])
def reset():
    global conversation_history
    conversation_history = []
    return jsonify({'status': 'reset'})


# ====== IMAGE DETECTION with Groq Cloud (Llama 4) ======
@app.route('/detect-image', methods=['POST'])
def detect_image():
    """Upload an image and get AI-powered detection using Groq cloud Llama 4."""
    if 'image' not in request.files:
        return jsonify({'error': 'No image file provided'}), 400
    
    file = request.files['image']
    if file.filename == '':
        return jsonify({'error': 'No image selected'}), 400
    
    try:
        image_bytes = file.read()
        
        # ⚡ Shorter prompt for faster cloud processing
        prompt = (
            "Analyze this image in detail. Cover:\n"
            " Who is it (name if famous)? Age? Gender? Expression?\n"
            
        )

        analysis = groq_vision(image_bytes, prompt)
        
        if not analysis:
            return jsonify({'error': 'Cloud vision analysis failed. Check your Groq API key.'}), 500

        analysis = clean_markdown(analysis)

        return jsonify({
            'success': True,
            'analysis': analysis,
            'filename': file.filename
        })

    except Exception as e:
        print(f"Image detection error: {e}")
        return jsonify({'error': f'Analysis failed: {str(e)}'}), 500


if __name__ == '__main__':
    print("🚀 GEN AI running with Llama 4 via Groq Cloud!")
    print(f"   Chat model: {CHAT_MODEL}")
    print(f"   Vision model: {VISION_MODEL}")
    print(f"   Groq API: ✅ Connected")
    app.run(debug=True, host='0.0.0.0', port=5000)
