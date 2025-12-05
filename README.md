# iMessage Wrapped 📱

A beautiful web app that analyzes your iMessage history and presents it like a "Spotify Wrapped" experience. View your messaging stats, top conversations, response times, emoji usage, and more!

## Quick Start (No Setup Required!)

**Download the pre-built app:**
1. Go to [Releases](../../releases)
2. Download `iMessageWrapped.zip`
3. Unzip and move `iMessageWrapped.app` to your Applications folder (or Desktop)
4. **First time opening:**
   - Right-click (or Control-click) on `iMessageWrapped.app`
   - Select "Open" from the menu
   - Click "Open" in the security dialog
   - (This bypasses the "Apple cannot check it" warning for unsigned apps)
5. Grant Full Disk Access when prompted (required to read Messages database)
   - System Settings → Privacy & Security → Full Disk Access
   - Toggle on for "iMessageWrapped"
6. Your stats will open in your browser automatically!

## Features

- 📊 **Message Statistics**: Total messages sent/received, busiest days
- 👥 **Top Conversations**: See who you message the most
- ⚡ **Response Time Analysis**: Track how quickly you and others respond
- 📝 **Average Message Length**: Word count per message
- 😀 **Top Emoji**: Most-used emoji across conversations
- 🔥 **Longest Streaks**: Consecutive days messaging with someone
- 📅 **Year-by-Year Breakdown**: View stats for specific years (2021-2025) or all time

---

## For Developers

### Requirements

- **macOS** (required - uses the Messages app database)
- **Python 3.7+**
- Access to your Messages database (usually granted automatically)

### Installation

1. **Clone or download this repository**
   ```bash
   cd ~/Desktop
   git clone <your-repo-url> imessage_wrapped
   cd imessage_wrapped
   ```

2. **Create a virtual environment**
   ```bash
   python3 -m venv venv
   ```

3. **Activate the virtual environment**
   ```bash
   source venv/bin/activate
   ```

4. **Install dependencies**
   ```bash
   pip install flask
   ```

### How to Run

#### Option 1: Run from Source (Recommended for Development)

1. **Activate the virtual environment** (if not already activated)
   ```bash
   source venv/bin/activate
   ```

2. **Run the Flask app**
   ```bash
   python imessage_wrapped.py
   ```

3. **Open your browser**
   - The app will automatically open in your default browser
   - Or manually navigate to: `http://127.0.0.1:5001`

4. **Stop the server**
   - Press `Ctrl+C` in the terminal

#### Option 2: Build Standalone macOS App

Build a double-clickable `.app` for distribution:

1. **Install PyInstaller**
   ```bash
   source venv/bin/activate
   pip install pyinstaller
   ```

2. **Build the app**
   ```bash
   pyinstaller imessage_wrapped.spec --clean
   cd dist
   zip -r iMessageWrapped.zip iMessageWrapped.app
   ```

3. **Create a GitHub Release**
   - Go to your repository → Releases → Create new release
   - Upload `dist/iMessageWrapped.zip`
   - Users can download and run without any setup!

## Troubleshooting

### Port Already in Use
If you see "Address already in use" error:
```bash
# Kill any existing Python processes
pkill -f "python.*imessage_wrapped"
# Then run again
python imessage_wrapped.py
```

### Permission Denied
If you get permission errors accessing the Messages database:
- Go to **System Settings** → **Privacy & Security** → **Full Disk Access**
- Add your terminal application (Terminal.app or iTerm.app)
- Restart your terminal and try again

### Messages Database Not Found
The app looks for your Messages database at:
```
~/Library/Messages/chat.db
```
If this file doesn't exist, you may not have used Messages on this Mac.

## How It Works

1. **Database Access**: The app creates a temporary copy of your Messages database to safely read from it
2. **Contact Matching**: Attempts to match phone numbers/emails with contact names from your Address Book
3. **Statistics Calculation**: 
   - Counts messages, words, and emoji
   - Calculates response times (only responses within 24 hours are counted)
   - Identifies conversation streaks and patterns
4. **Web Display**: Presents everything in a beautiful, interactive web interface

## Privacy

- ✅ All data stays **local on your computer**
- ✅ No data is sent to any external servers
- ✅ The app only reads your Messages database (doesn't modify it)
- ✅ Creates a temporary copy that's deleted after use

## Statistics Explained

- **Avg Words**: Average number of words per text message (excludes attachments/reactions)
- **Your Response**: Average time (in hours) it takes you to respond to their messages
- **Their Response**: Average time (in hours) it takes them to respond to your messages
- **Active Days**: Number of unique days you've exchanged messages
- **Response times only count replies within 24 hours** (ignores delayed responses)

## License

MIT License - Feel free to use and modify!

## Credits

Built with Python, Flask, and SQLite. Inspired by Spotify Wrapped.
