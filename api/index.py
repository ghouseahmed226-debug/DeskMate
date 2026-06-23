from http.server import BaseHTTPRequestHandler
import sys
import io
import os
import tempfile
import shutil
from pathlib import Path

# Add parent directory to path so we can import run_demo
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # We must copy mock_data to /tmp because Vercel functions are read-only except /tmp
        base_dir = Path(__file__).resolve().parent.parent
        src_mock_data = base_dir / "mock_data"
        tmp_mock_data = Path("/tmp/mock_data")
        
        # Always use a fresh copy for the demo
        if tmp_mock_data.exists():
            shutil.rmtree(tmp_mock_data)
        shutil.copytree(src_mock_data, tmp_mock_data)
        
        # Patch the paths in mcp_server.personal_data_mcp_server
        import mcp_server.personal_data_mcp_server as mcp_server
        mcp_server.DATA_DIR = tmp_mock_data
        mcp_server.AUDIT_LOG_PATH = Path("/tmp/audit_log.jsonl")
        mcp_server.CALENDAR_FILE = tmp_mock_data / "calendar.json"
        mcp_server.EMAILS_FILE = tmp_mock_data / "emails.json"
        mcp_server.CONTACTS_FILE = tmp_mock_data / "contacts.json"
        mcp_server.TASKS_FILE = tmp_mock_data / "tasks.json"

        import run_demo
        
        # Capture stdout
        old_stdout = sys.stdout
        sys.stdout = my_stdout = io.StringIO()
        
        try:
            run_demo.reset_audit_log()
            run_demo.print_permissions_table()
            run_demo.run_conversation()
            run_demo.demonstrate_security_boundary()
            run_demo.print_audit_log()
        except Exception as e:
            print(f"Error: {e}")
        finally:
            sys.stdout = old_stdout
            
        output = my_stdout.getvalue()
        
        self.send_response(200)
        self.send_header('Content-type', 'text/plain; charset=utf-8')
        self.end_headers()
        self.wfile.write(output.encode('utf-8'))
        return
