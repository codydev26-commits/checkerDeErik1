import http.server
import socketserver
import urllib.request
import urllib.parse
import json
import os
import sys

PORT = 8000

class ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    pass

class CheckerHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # Allow cross-origin requests from any local file or domain
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-Requested-With')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        
        # 1. API: Ping to detect server activity
        if parsed_url.path == '/api/ping':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'ok'}).encode('utf-8'))
            return
            
        # 2. API: Verify account against host
        elif parsed_url.path == '/api/verify':
            query = urllib.parse.parse_qs(parsed_url.query)
            host = query.get('host', [''])[0]
            username = query.get('username', [''])[0]
            password = query.get('password', [''])[0]
            
            if not host or not username or not password:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'Missing parameters')
                return
                
            target_url = f"{host}/player_api.php?username={urllib.parse.quote(username)}&password={urllib.parse.quote(password)}"
            try:
                req = urllib.request.Request(
                    target_url, 
                    headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                )
                with urllib.request.urlopen(req, timeout=4.5) as response:
                    data = response.read()
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(data)
            except Exception as e:
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                error_resp = {'error': True, 'message': str(e)}
                self.wfile.write(json.dumps(error_resp).encode('utf-8'))
            return

        # 2.5 API: Verify panel login (reseller account) and return credits
        elif parsed_url.path == '/api/verify_panel':
            query = urllib.parse.parse_qs(parsed_url.query)
            host = query.get('host', [''])[0]
            username = query.get('username', [''])[0]
            password = query.get('password', [''])[0]

            if not host or not username or not password:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'Missing parameters')
                return

            credits = "N/A"
            is_valid = False

            # Normalize host URL
            base_url = host.rstrip('/')
            
            # Formulate possible reseller login endpoints and parameters
            # Xtream UI / XUI One panels use login pages and API routes
            import urllib.request as urllib_request
            import http.cookiejar as cookiejar
            
            cj = cookiejar.CookieJar()
            opener = urllib_request.build_opener(urllib_request.HTTPCookieProcessor(cj))
            
            # List of login paths and payload keys to try
            login_attempts = [
                {"path": "/resellers/login", "payload": {"username": username, "password": password, "login": ""}},
                {"path": "/login.php", "payload": {"username": username, "password": password}},
                {"path": "/login", "payload": {"username": username, "password": password}},
                {"path": "/admin/login", "payload": {"username": username, "password": password}}
            ]

            for attempt in login_attempts:
                login_url = f"{base_url}{attempt['path']}"
                post_data = urllib.parse.urlencode(attempt['payload']).encode('utf-8')
                
                try:
                    req = urllib_request.Request(
                        login_url,
                        data=post_data,
                        headers={
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                            'Content-Type': 'application/x-www-form-urlencoded',
                            'Referer': login_url
                        },
                        method='POST'
                    )
                    
                    with opener.open(req, timeout=5.0) as response:
                        body = response.read().decode('utf-8', errors='ignore')
                        final_url = response.geturl()
                        
                        # A successful login redirects to dashboard, resellers home, or has credits/logout indications
                        # Also check if redirection happens, or dashboard keywords appear
                        is_dashboard_redirect = any(kw in final_url.lower() for kw in ["dashboard", "reseller", "manage", "index.php", "home"])
                        has_dashboard_elements = any(kw in body.lower() for kw in ["logout", "credits", "créditos", "creditos", "saldo", "balance", "profile", "historial"])
                        
                        if is_dashboard_redirect or has_dashboard_elements:
                            is_valid = True
                            
                        # Extract credit values using flexible patterns matching XUI / Xtream UI layouts
                        patterns = [
                            r'(?:credits|cr&eacute;ditos|creditos|saldo|balance)\s*[:\-\u25ba\u279c]*\s*<b>?\s*([\d.,]+)\s*</b>?',
                            r'class="[^"]*credits[^"]*"[^>]*>\s*([\d.,]+)',
                            r'id="[^"]*credits[^"]*"[^>]*>\s*([\d.,]+)',
                            r'<span>\s*([\d.,]+)\s*</span>\s*<small>\s*(?:Credits|Créditos|Balance)\s*</small>',
                            r'(?:credits|cr&eacute;ditos|creditos|saldo|balance)\s*[:\-]*\s*<span>\s*([\d.,]+)\s*</span>'
                        ]
                        
                        for pat in patterns:
                            credits_match = re.search(pat, body, re.IGNORECASE)
                            if credits_match:
                                credits = credits_match.group(1)
                                is_valid = True
                                break
                                
                        # Fetch dashboard pages to scrape credits if logged in but credits are not on current page
                        if is_valid and credits == "N/A":
                            for dashboard_path in ["/resellers/dashboard", "/resellers", "/dashboard", "/index.php"]:
                                try:
                                    db_url = f"{base_url}{dashboard_path}"
                                    req_db = urllib_request.Request(
                                        db_url,
                                        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                                    )
                                    with opener.open(req_db, timeout=4.0) as db_resp:
                                        db_body = db_resp.read().decode('utf-8', errors='ignore')
                                        for pat in patterns:
                                            credits_match = re.search(pat, db_body, re.IGNORECASE)
                                            if credits_match:
                                                credits = credits_match.group(1)
                                                break
                                    if credits != "N/A":
                                        break
                                except:
                                    pass
                                    
                        if is_valid:
                            break
                except Exception as e:
                    # Continue trying other paths
                    continue

            # Fallback using player_api.php or reseller dashboard API if page verification failed
            if not is_valid:
                try:
                    # Xtream codes player API
                    api_check_url = f"{base_url}/player_api.php?username={urllib.parse.quote(username)}&password={urllib.parse.quote(password)}"
                    req2 = urllib_request.Request(
                        api_check_url,
                        headers={'User-Agent': 'Mozilla/5.0'}
                    )
                    with urllib.request.urlopen(req2, timeout=4.5) as response2:
                        res_json = json.loads(response2.read().decode('utf-8'))
                        user_info = res_json.get('user_info', {})
                        if user_info and (user_info.get('status', '').lower() == 'active' or 'credits' in user_info):
                            is_valid = True
                            credits = str(user_info.get('credits', 'N/A'))
                            if credits == 'N/A' and 'credits' in res_json.get('server_info', {}):
                                credits = str(res_json['server_info']['credits'])
                except:
                    pass

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': is_valid, 'credits': credits}).encode('utf-8'))
            return
            
        # 3. API: Check host online status
        elif parsed_url.path == '/api/check_host':
            query = urllib.parse.parse_qs(parsed_url.query)
            host = query.get('host', [''])[0]
            
            if not host:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'Missing host parameter')
                return
                
            online = False
            # Check with player_api first
            try:
                req = urllib.request.Request(
                    host + '/player_api.php', 
                    headers={'User-Agent': 'Mozilla/5.0'}
                )
                with urllib.request.urlopen(req, timeout=3.5) as response:
                    online = True
            except Exception:
                # Fallback to root index
                try:
                    req = urllib.request.Request(
                        host + '/', 
                        headers={'User-Agent': 'Mozilla/5.0'}
                    )
                    with urllib.request.urlopen(req, timeout=3.5) as response:
                        online = True
                except Exception:
                    pass

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'online': online}).encode('utf-8'))
            return

        # Redirect index request to Michecker.html
        if parsed_url.path in ('/', '/index.html'):
            self.path = '/Michecker.html'
            
        return super().do_GET()

if __name__ == '__main__':
    # Set current working directory to script location
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    
    # Configure and start Threading Server
    handler = CheckerHandler
    try:
        with ThreadingTCPServer(("", PORT), handler) as httpd:
            print("="*60)
            print(f" IPTV Checker Server iniciado exitosamente.")
            print(f" Servidor corriendo en: http://localhost:{PORT}")
            print(f" Evacion de CORS activa mediante backend Python.")
            print("="*60)
            
            # Automatically open browser
            import webbrowser
            webbrowser.open(f"http://localhost:{PORT}")
            
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor detenido por el usuario.")
        sys.exit(0)
    except Exception as e:
        print(f"Error al iniciar servidor: {e}")
        sys.exit(1)
