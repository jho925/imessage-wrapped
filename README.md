# iMessage Wrapped 📱

A web app that analyzes your iMessage history and presents it in a nice UI.

## Features

- **Message Statistics**: Total messages sent/received, busiest days
- **Top Conversations**: See who you message the most
- **Response Time Analysis**: Track how quickly you and others respond
- **Average Message Length**: Word count per message
- **Top Emoji**: Most-used emoji across conversations
- **Longest Streaks**: Consecutive days messaging with someone
- **Year-by-Year Breakdown**: View stats for specific years (2021-2025) or all time

## Requirements

- **macOS** (required - uses the Messages app database)
- **Python 3.7+**
- Access to your Messages database (usually granted automatically)

## Installation

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

## How to Run

1. **Activate the virtual environment** (if not already activated)
   ```bash
   source venv/bin/activate
   ```

2. **Run the Flask app**
   ```bash
   python imessage_wrapped.py
   ```

3. **Open your browser**
   - Navigate to: `http://127.0.0.1:5001`
   - The app will automatically read your Messages database and display your stats

4. **Stop the server**
   - Press `Ctrl+C` in the terminal

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

## Privacy

- All data stays **local on your computer**
- No data is sent to any external servers
- The app only reads your Messages database without modifying it

## License

MIT License - Feel free to use and modify!

