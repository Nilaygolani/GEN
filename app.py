from flask import Flask, render_template, request, jsonify
import google.generativeai as genai
from datetime import datetime
import pytz
import re
import html as html_mod

app = Flask(__name__)

# 🔐 API Key Configuration
API_KEY = "AQ.Ab8RN6Ib5M5Ufa4ErQJQ8AIa9xnlm1laqV-RMZIZiOZ_nv1M1Q"
genai.configure(api_key=API_KEY)


# 🧠 Model Initialization
try:
    model = genai.GenerativeModel('gemini-3.5-flash-lite')
    print("✅ Model loaded successfully!")
except Exception as e:
    print(f"⚠️ Using fallback model. Error: {e}")
    model = genai.GenerativeModel('gemini-1.5-flash')


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
    # ***text*** → text
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'\1', text)
    # **text** → text
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    
    # ====== STEP 4: Process line by line ======
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        # Bullet: "* text" → "• text"
        if re.match(r'^\s*\*\s+', line):
            line = re.sub(r'^(\s*)\*\s+', r'\1• ', line)
        # Bullet: "- text" → "→ text"
        elif re.match(r'^\s*-\s+', line):
            line = re.sub(r'^(\s*)- ', r'\1→ ', line)
        else:
            # Remove single * used for italic (but not bullets)
            line = re.sub(r'\*([^*]+)\*', r'\1', line)
        
        # Remove any remaining stray * characters
        line = line.replace('*', '')
        
        # Remove heading markers (# ## ### etc)
        line = re.sub(r'^#+\s+', '', line)
        
        # Remove horizontal rules (---, ***, ___)
        if re.match(r'^\s*[-*_]{3,}\s*$', line.strip()):
            continue
        
        # Remove blockquotes >
        line = re.sub(r'^\s*>\s+', '', line)
        
        # Remove markdown links [text](url) → text
        line = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', line)
        
        cleaned_lines.append(line)
    
    text = '\n'.join(cleaned_lines)
    
    # ====== STEP 5: Clean up extra blank lines ======
    text = re.sub(r'\n{4,}', '\n\n\n', text)
    
    # ====== STEP 6: Convert newlines to HTML breaks ======
    # Split by code block placeholders to protect them
    parts = re.split(r'(%%CB_\d+%%)', text)
    for i in range(len(parts)):
        if not re.match(r'%%CB_\d+%%', parts[i]):
            # Double newline = paragraph break
            parts[i] = parts[i].replace('\n\n', '</p><p>')
            # Single newline = line break
            parts[i] = parts[i].replace('\n', '<br>')
    text = ''.join(parts)
    
    # Wrap in paragraph if needed
    if not text.startswith('<'):
        text = f'<p>{text}</p>'
    
    # ====== STEP 7: Restore code blocks ======
    for i, block in enumerate(code_blocks):
        text = text.replace(f'%%CB_{i}%%', block)
    for i, block in enumerate(inline_codes):
        text = text.replace(f'%%IC_{i}%%', block)
    
    # Clean up
    text = re.sub(r'<p>\s*<br>\s*', '<p>', text)
    text = re.sub(r'\s*<br>\s*</p>', '</p>', text)
    text = re.sub(r'<br><br>', '<br>', text)
    
    return text.strip()


conversation_history = []
MAX_PAIRS = 10
MAX_ENTRIES = MAX_PAIRS * 2

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
        # ====== Add current date context ======
        ist = pytz.timezone('Asia/Kolkata')
        current_date = datetime.now(ist).strftime("%A, %d %B %Y at %I:%M %p")
        
        augmented_message = (
            f"[Current Date & Time: {current_date}]\n"
            f"User: {user_message}"
        )
        
        chat_session = model.start_chat(history=conversation_history)
        response = chat_session.send_message(augmented_message)
        bot_reply = response.text
        
        # Clean the reply
        if bot_reply.startswith("User:"):
            bot_reply = bot_reply[5:].strip()
        
        # ====== CLEAN MARKDOWN ======
        bot_reply = clean_markdown(bot_reply)
        
        conversation_history = chat_session.history
        if len(conversation_history) > MAX_ENTRIES:
            conversation_history = conversation_history[-MAX_ENTRIES:]
        
        return jsonify({'reply': bot_reply})
    
    except Exception as e:
        return jsonify({'reply': f'Sorry, I encountered an error: {str(e)}'}), 500

@app.route('/reset', methods=['POST'])
def reset():
    global conversation_history
    conversation_history = []
    return jsonify({'status': 'reset'})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
