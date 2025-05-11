from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import chess
import chess.engine
import chess.pgn
import statistics
import os
from io import StringIO
from typing import List, Dict

app = Flask(__name__)
CORS(app)

STOCKFISH_PATH = os.path.join(
    os.path.dirname(__file__), 
    "stockfish", 
    "stockfish-windows-x86-64-avx2.exe"
)
engine = None

def get_engine():
    global engine
    if engine is None or engine.ping() is None:
        try:
            engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
        except Exception as e:
            app.logger.error(f"Failed to initialize Stockfish: {str(e)}")
            raise
    return engine

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    try:
        engine = get_engine()
    except:
        return jsonify({"error": "Engine initialization failed"}), 500
    
    pgn_text = ""
    
    if 'pgnFile' in request.files:
        file = request.files['pgnFile']
        if file and file.filename.endswith('.pgn'):
            pgn_text = file.read().decode('utf-8')
        else:
            return jsonify({"error": "Invalid file type"}), 400
    elif 'pgnText' in request.form:
        pgn_text = request.form['pgnText']
    else:
        return jsonify({"error": "No PGN provided"}), 400
    
    try:
        game = chess.pgn.read_game(StringIO(pgn_text))
        if not game:
            return jsonify({"error": "Invalid PGN format"}), 400

        board = game.board()
        white_losses = []
        black_losses = []
        moves = []
        suspicious_moves = []

        for move in game.mainline_moves():
            # Analysis logic
            best_analysis = engine.analyse(board, chess.engine.Limit(depth=18))
            best_score = best_analysis["score"].relative.score(mate_score=100000)
            
            played_analysis = engine.analyse(
                board, 
                chess.engine.Limit(depth=18), 
                root_moves=[move]
            )
            played_score = played_analysis["score"].relative.score(mate_score=100000)
            
            loss = max(0, best_score - played_score) if None not in (best_score, played_score) else 0
            player = "white" if board.turn == chess.WHITE else "black"
            
            # Record move data
            move_data = {
                "player": player,
                "move": move.uci(),
                "centipawn_loss": loss,
                "suspicious": loss < 10
            }
            moves.append(move_data)
            
            if loss < 10:
                suspicious_moves.append({
                    "player": player,
                    "move": move.uci(),
                    "centipawn_loss": loss
                })

            if player == "white":
                white_losses.append(loss)
            else:
                black_losses.append(loss)
            
            board.push(move)

        # Calculate statistics
        def calculate_stats(losses):
            if not losses:
                return {"avg": 0.0, "engine_likelihood": 0.0}
            avg = sum(losses) / len(losses)
            perfect = sum(1 for l in losses if l < 10) / len(losses)
            stdev = statistics.stdev(losses) if len(losses) > 1 else 0
            engine_score = min(1.0, (perfect * 0.7) + (1/(1+stdev) * 0.3))
            return {"avg": avg, "engine_likelihood": engine_score}

        white_stats = calculate_stats(white_losses)
        black_stats = calculate_stats(black_losses)

        return jsonify({
            "white": game.headers.get("White", "Unknown"),
            "black": game.headers.get("Black", "Unknown"),
            "date": game.headers.get("Date", "Unknown"),
            "result": game.headers.get("Result", "*"),
            "players": {
                "white": {
                    "engine_likelihood": white_stats["engine_likelihood"],
                    "avg_loss": white_stats["avg"]
                },
                "black": {
                    "engine_likelihood": black_stats["engine_likelihood"],
                    "avg_loss": black_stats["avg"]
                }
            },
            "moves": moves,
            "suspicious_moves": suspicious_moves
        })

    except Exception as e:
        return jsonify({
            "error": str(e),
            "moves": [],
            "suspicious_moves": []
        })

@app.teardown_appcontext
def shutdown_engine(exception=None):
    global engine
    if engine is not None:
        try:
            engine.quit()
        except chess.engine.EngineTerminatedError:
            pass
        finally:
            engine = None

if __name__ == '__main__':
    try:
        get_engine()
        app.run(host='0.0.0.0', port=5000, threaded=True)
    finally:
        shutdown_engine()