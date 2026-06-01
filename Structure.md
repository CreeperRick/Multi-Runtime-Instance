```project/
├── app.py                 # Main Flask application with routes and SocketIO
├── bootstrap.py           # Instance discovery, repair, and initialization
├── requirements.txt       # Python dependencies
├── templates/
│   └── index.html        # Single-page UI with instance management
├── static/
│   ├── css/
│   │   └── style.css     # Styling and responsive layout
│   └── js/
│       └── app.js        # Client-side logic, API calls, real-time updates
├── instances/            # Auto-created on first run
│   └── Default/          # Default instance with all subdirectories
├── uploads/              # Temporary upload storage
├── logs/                 # Global logs (instance-specific logs go inside instances)
├── history/              # Global history (instance-specific history goes inside instances)
└── temp/                 # Temporary files```
