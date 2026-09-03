from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.errors import UniqueViolation
import os
import json
import csv
import io
import re
from datetime import datetime

# COLE A SUA URI DO SUPABASE AQUI EMBAIXO:
DATABASE_URL = "postgresql://postgres.yeyjyjwwbgvvvquahxjw:91316994Rise2028*@aws-0-us-east-2.pooler.supabase.com:6543/postgres"

app = Flask(__name__)
CORS(app)

def get_db_connection():
    # Conecta ao PostgreSQL usando o cursor que retorna dicionários (como o row_factory do SQLite)
    conn = psycopg2.connect(DATABASE_URL)
    return conn

def normalizar_uc(valor):
    if valor is None:
        return ""
    texto = str(valor).strip()
    texto = texto.replace(' ', '').replace('-', '').replace('.', '')
    return re.sub(r'[^0-9]', '', texto)

def extrair_ucs_do_payload(payload):
    if payload is None:
        return []
    if isinstance(payload, dict):
        valores = payload.get('ucs') or payload.get('lista') or payload.get('base') or payload.get('dados') or []
        if isinstance(valores, str):
            return parsear_lista_ucs(valores)
        payload = valores
    if isinstance(payload, str):
        return parsear_lista_ucs(payload)
    if isinstance(payload, list):
        itens = payload
    else:
        itens = [payload]
    ucs = []
    for item in itens:
        if isinstance(item, dict):
            for chave in ['uc', 'codigo', 'codigo_uc', 'numero', 'numero_uc', 'valor']:
                if chave in item and item[chave] not in (None, ''):
                    valor = normalizar_uc(item[chave])
                    if valor:
                        ucs.append(valor)
                    break
        elif isinstance(item, (str, int)):
            valor = normalizar_uc(item)
            if valor:
                ucs.append(valor)
    return sorted(set(ucs))

def extrair_ucs_do_arquivo(nome_arquivo, conteudo):
    nome = (nome_arquivo or '').lower()
    texto = conteudo.decode('utf-8-sig', errors='ignore')
    if nome.endswith('.json'):
        try:
            payload = json.loads(texto)
            return extrair_ucs_do_payload(payload)
        except json.JSONDecodeError:
            return []
    if nome.endswith('.csv') or nome.endswith('.txt'):
        reader = csv.reader(io.StringIO(texto))
        linhas = list(reader)
        if not linhas:
            return []
        cabecalho = [str(coluna).strip().lower() for coluna in linhas[0]]
        indice_uc = None
        for idx, coluna in enumerate(cabecalho):
            if 'uc' in coluna or 'codigo' in coluna or 'numero' in coluna:
                indice_uc = idx
                break
        ucs = []
        for linha in linhas[1:] if indice_uc is not None else linhas:
            if not linha:
                continue
            valor = linha[indice_uc] if indice_uc is not None and len(linha) > indice_uc else linha[0]
            valor = normalizar_uc(valor)
            if valor:
                ucs.append(valor)
        return sorted(set(ucs))
    return []

def parsear_lista_ucs(texto):
    if texto is None:
        return []
    if isinstance(texto, (list, tuple, set)):
        lista = texto
    else:
        conteudo = str(texto).replace('\ufeff', '')
        partes = re.split(r'[\n,;\t\r\|]+', conteudo)
        lista = [parte for parte in partes if parte.strip()]
    ucs = []
    for item in lista:
        valor = normalizar_uc(item)
        if valor:
            ucs.append(valor)
    return sorted(set(ucs))

def importar_ucs_para_banco(ucs):
    if not ucs:
        return {"novos": 0, "duplicados": 0, "total": 0}
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('DELETE FROM ucs')
    conn.commit()
    
    novos = 0
    duplicados = 0
    lista_final = sorted(set(ucs))
    
    for uc in lista_final:
        uc_limpo = normalizar_uc(uc)
        if not uc_limpo:
            continue
        try:
            cursor.execute(
                'INSERT INTO ucs (uc, data_importacao, material, peso_liquido) VALUES (%s, %s, %s, %s)',
                (uc_limpo, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), '', 0)
            )
            novos += 1
        except UniqueViolation:
            conn.rollback() # No Postgre precisa dar rollback no erro antes de continuar
            duplicados += 1
            
    cursor.execute('SELECT COUNT(*) FROM ucs')
    total = cursor.fetchone()[0]
    conn.commit()
    cursor.close()
    conn.close()
    return {"novos": novos, "duplicados": duplicados, "total": total}

def registrar_log_login(matricula, nome, sucesso, origem='web'):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        '''
        INSERT INTO logs_login (matricula, nome, data_hora, sucesso, origem)
        VALUES (%s, %s, %s, %s, %s)
        ''',
        (
            (matricula or '').strip(),
            (nome or '').strip(),
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            1 if sucesso else 0,
            origem,
        )
    )
    conn.commit()
    cursor.close()
    conn.close()

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    # No PostgreSQL usamos SERIAL em vez de AUTOINCREMENT
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bipagens (
            id SERIAL PRIMARY KEY,
            operador TEXT,
            nome TEXT,
            posicao TEXT,
            uc TEXT,
            seq INTEGER,
            data_hora TEXT,
            data_sincronizacao TEXT,
            material TEXT,
            peso_liquido REAL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ucs (
            id SERIAL PRIMARY KEY,
            uc TEXT NOT NULL UNIQUE,
            data_importacao TEXT,
            material TEXT,
            peso_liquido REAL,
            ativo INTEGER DEFAULT 1
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id SERIAL PRIMARY KEY,
            nome TEXT NOT NULL,
            matricula TEXT NOT NULL UNIQUE,
            senha_hash TEXT NOT NULL,
            ativo INTEGER DEFAULT 1,
            data_criacao TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS logs_login (
            id SERIAL PRIMARY KEY,
            matricula TEXT,
            nome TEXT,
            data_hora TEXT,
            sucesso INTEGER,
            origem TEXT DEFAULT 'web'
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS documentos (
            id SERIAL PRIMARY KEY,
            numero TEXT NOT NULL UNIQUE,
            descricao TEXT,
            posicoes TEXT
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_ucs_uc ON ucs (uc)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_usuarios_matricula ON usuarios (matricula)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_logs_login_data ON logs_login (data_hora)')
    conn.commit()
    cursor.close()
    conn.close()

@app.route('/documentos/importar', methods=['POST'])
def importar_documentos():
    dados = request.get_json(silent=True) or {}
    texto = dados.get('texto', '')
    if not texto.strip():
        return jsonify({"erro": "Nenhum texto enviado."}), 400
    linhas = texto.strip().split('\n')
    conn = get_db_connection()
    cursor = conn.cursor()
    inseridos = 0
    atualizados = 0
    for linha in linhas:
        if not linha.strip(): continue
        partes = linha.split('/')
        if len(partes) >= 3:
            numero = partes[0].strip()
            descricao = partes[1].strip()
            posicoes = partes[2].strip()
            try:
                cursor.execute('INSERT INTO documentos (numero, descricao, posicoes) VALUES (%s, %s, %s)', (numero, descricao, posicoes))
                inseridos += 1
            except UniqueViolation:
                conn.rollback()
                cursor.execute('UPDATE documentos SET descricao = %s, posicoes = %s WHERE numero = %s', (descricao, posicoes, numero))
                atualizados += 1
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"mensagem": f"Documentos processados: {inseridos} novos, {atualizados} atualizados."}), 200

@app.route('/documentos/validar/<numero>', methods=['GET'])
def validar_documento(numero):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute('SELECT numero, descricao, posicoes FROM documentos WHERE numero = %s', (numero.strip(),))
    doc = cursor.fetchone()
    cursor.close()
    conn.close()
    if doc:
        lista_posicoes = [p.strip() for p in doc['posicoes'].split(';') if p.strip()]
        return jsonify({"existe": True, "numero": doc['numero'], "descricao": doc['descricao'], "posicoes": lista_posicoes}), 200
    else:
        return jsonify({"existe": False, "erro": "Documento não encontrado."}), 404

# Substituimos a rota principal para abrir o painel direto, garantindo segurança!
@app.route('/')
def index():
    return send_from_directory('.', 'painel.html')

@app.route('/ucs/importar', methods=['POST'])
def importar_ucs():
    arquivo = request.files.get('arquivo') if request.files else None
    payload = request.get_json(silent=True)
    texto = request.form.get('ucs') if request.form else None
    if arquivo and arquivo.filename:
        ucs = extrair_ucs_do_arquivo(arquivo.filename, arquivo.read())
    elif payload is not None:
        ucs = extrair_ucs_do_payload(payload)
        if not ucs and isinstance(payload, dict):
            ucs = parsear_lista_ucs(payload.get('ucs') or payload.get('base') or payload.get('lista') or payload.get('dados'))
    elif texto:
        ucs = parsear_lista_ucs(texto)
    else:
        return jsonify({"erro": "Nenhum arquivo ou payload enviado."}), 400
    if not ucs:
        return jsonify({"erro": "Nenhuma UC válida foi encontrada no arquivo."}), 400
    resultado = importar_ucs_para_banco(ucs)
    return jsonify({
        "mensagem": "Base de UCs importada com sucesso.",
        "novos": resultado['novos'],
        "duplicados": resultado['duplicados'],
        "total": resultado['total']
    }), 200

@app.route('/ucs', methods=['GET'])
def listar_ucs():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute('SELECT id, uc, data_importacao, material, peso_liquido FROM ucs ORDER BY id DESC')
    registros = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify({
        "total": len(registros),
        "ucs": [dict(row) for row in registros]
    })

@app.route('/ucs/validar/<uc>', methods=['GET'])
def validar_uc(uc):
    uc_normalizada = normalizar_uc(uc)
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute('SELECT id, uc, material, peso_liquido FROM ucs WHERE uc = %s', (uc_normalizada,))
    registro = cursor.fetchone()
    cursor.close()
    conn.close()
    if registro is None:
        return jsonify({"existe": False, "uc": uc_normalizada})
    return jsonify({"existe": True, "uc": uc_normalizada, "material": registro['material'], "peso_liquido": registro['peso_liquido']})

@app.route('/usuarios/registrar', methods=['POST'])
def registrar_usuario():
    dados = request.get_json(silent=True) or {}
    nome = (dados.get('nome') or '').strip()
    matricula = str(dados.get('matricula') or '').strip().upper()
    if not nome or not matricula:
        return jsonify({"erro": "Nome e matrícula são obrigatórios."}), 400
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            'INSERT INTO usuarios (nome, matricula, senha_hash, data_criacao) VALUES (%s, %s, %s, %s)',
            (nome, matricula, '', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        )
        conn.commit()
        retorno = {"mensagem": "Usuário cadastrado com sucesso."}
        status_code = 200
    except UniqueViolation:
        conn.rollback()
        retorno = {"erro": "Matrícula já cadastrada."}
        status_code = 409
    finally:
        cursor.close()
        conn.close()
    return jsonify(retorno), status_code

@app.route('/login', methods=['POST'])
def login_usuario():
    dados = request.get_json(silent=True) or {}
    matricula = str(dados.get('matricula') or '').strip().upper()
    nome = (dados.get('nome') or '').strip()
    if not matricula or not nome:
        registrar_log_login(matricula, nome, False)
        return jsonify({"erro": "Matrícula e nome são obrigatórios."}), 400
    registrar_log_login(matricula, nome, True)
    return jsonify({
        "ok": True,
        "matricula": matricula,
        "nome": nome,
        "mensagem": "Login realizado com sucesso."
    }), 200

@app.route('/ucs/registrar', methods=['POST'])
def registrar_uc_manual():
    dados = request.get_json(silent=True) or {}
    uc = normalizar_uc(dados.get('uc'))
    material = (dados.get('material') or '').strip()
    peso = dados.get('peso_liquido')
    if not uc:
        return jsonify({"erro": "UC obrigatória."}), 400
    if not material:
        return jsonify({"erro": "Material obrigatório."}), 400
    try:
        peso_float = float(str(peso).replace(',', '.')) if peso not in (None, '') else 0
    except ValueError:
        return jsonify({"erro": "Peso líquido inválido."}), 400
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            'INSERT INTO ucs (uc, data_importacao, material, peso_liquido) VALUES (%s, %s, %s, %s)',
            (uc, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), material, peso_float)
        )
        conn.commit()
        retorno = {"mensagem": "UC registrada com sucesso.", "existe": True, "uc": uc}
    except UniqueViolation:
        conn.rollback()
        cursor.execute(
            'UPDATE ucs SET material = %s, peso_liquido = %s WHERE uc = %s',
            (material, peso_float, uc)
        )
        conn.commit()
        retorno = {"mensagem": "UC já existia e foi atualizada com os dados informados.", "existe": True, "uc": uc}
    finally:
        cursor.close()
        conn.close()
    return jsonify(retorno), 200

@app.route('/sincronizar', methods=['POST'])
def sincronizar_dados():
    dados = request.json
    if not dados or not isinstance(dados, list):
        return jsonify({"erro": "Formato de dados inválido. Esperado uma lista."}), 400
    conn = get_db_connection()
    cursor = conn.cursor()
    sucessos = 0
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for item in dados:
        try:
            cursor.execute('SELECT id FROM bipagens WHERE posicao = %s AND uc = %s AND seq = %s', (item['posicao'], item['uc'], item['seq']))
            existe = cursor.fetchone()
            if not existe:
                cursor.execute('''
                    INSERT INTO bipagens (operador, nome, posicao, uc, seq, data_hora, data_sincronizacao)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                ''', (item['operador'], item['nome'], item['posicao'], item['uc'], item['seq'], item['dataHora'], agora))
                sucessos += 1
        except Exception as e:
            print(f"Erro ao inserir item {item['uc']}: {e}")
            conn.rollback() # Em caso de erro, dá rollback no laço atual
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"mensagem": "Sincronização concluída", "inseridos": sucessos}), 200

@app.route('/dados', methods=['GET'])
def listar_dados():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute('SELECT * FROM bipagens ORDER BY id DESC')
    bipagens = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify([dict(row) for row in bipagens])

@app.route('/<path:filename>')
def serve_static(filename):
    return send_from_directory('.', filename)

if __name__ == '__main__':
    init_db()
    # Para testes na máquina local usa a porta 5050. Na nuvem, usa a porta que o provedor fornecer (geralmente variável de ambiente PORT)
    port = int(os.environ.get("PORT", 5050))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False, threaded=True)