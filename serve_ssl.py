"""
Development SSL Server for Saudi Places of Worship Map.
Delegates to the full backend server to provide both API and frontend with HTTPS.
"""

import sys
from server import main

if __name__ == "__main__":
    # If a port number was passed as the first positional argument, rewrite it for argparse
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        sys.argv = [sys.argv[0], "--port", sys.argv[1]]
    main()
