import base64
import json
import os
from dotenv import load_dotenv
import google.generativeai as genai
import streamlit as st
import streamlit.components.v1 as components
from core.engine import build_from_dict, export_stl

# .env ファイルの読み込み
load_dotenv()

st.set_page_config(page_title="AI CAD Generator", layout="wide")

st.title("🤖 AI CAD Generator - 自然言語 3D モデリング")
st.caption("言葉で指定するだけで、AI が CAD パラメータを自動生成し 3D モデルを構築します。")

# ---------------------------------------------------------
# Gemini API の初期化
# ---------------------------------------------------------
api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    api_key = st.sidebar.text_input("Gemini API Key を入力", type="password")

if api_key:
    genai.configure(api_key=api_key)

SYSTEM_PROMPT = """
あなたは 3D CAD エンジン (cad-core) のための JSON パラメータ生成 AI です。
ユーザーの日本語の指示を解釈し、以下の構造を持つ JSON のみを出力してください。
余計な解説文や Markdown のコードブロック (```json など) は一切付けず、純粋な JSON テキストのみを返してください。

【JSON 構造仕様】
{
  "units": "mm",
  "primitives": [
    {
      "id": "一意のID (例: b1, c1)",
      "type": "box" | "cylinder" | "sphere",
      "params": {
        // box の場合: "length", "width", "height", "position": [x, y, z]
        // cylinder の場合: "radius", "height", "position": [x, y, z]
        // sphere の場合: "radius", "position": [x, y, z]
      }
    }
  ],
  "operations": [
    {
      "op": "cut" | "union" | "intersect" | "fillet" | "chamfer",
      "base": "ベースの primitive ID",
      "tool": "削る/くっつける primitive ID",
      "result_id": "生成される結果 ID"
    }
  ]
}

【規則】
1. オプションで operations が不要な単一形状の場合は operations は空配列 [] にします。
2. 穴を貫通させる場合、cylinder の height は base の形状より少し長くしてください。
"""

def generate_cad_json(prompt_text: str) -> dict:
    model = genai.GenerativeModel(
        model_name="gemini-3.6-flash",
        system_instruction=SYSTEM_PROMPT,
        generation_config={"response_mime_type": "application/json"}
    )
    response = model.generate_content(prompt_text)
    return json.loads(response.text)

# ---------------------------------------------------------
# UI レイアウト
# ---------------------------------------------------------
col_left, col_right = st.columns([1, 1])

param_dict = None

with col_left:
    st.subheader("💬 指示を入力")
    default_input = "20x10x10の箱の真ん中に、半径2の円柱で貫通穴をあけて"
    user_prompt = st.text_area("3Dモデルのプロンプト", value=default_input, height=100)
    generate_btn = st.button("🚀 3D モデルを生成", type="primary")

    if generate_btn:
        if not api_key:
            st.error("Gemini API Key が見つかりません。.env ファイルかサイドバーでキーを設定してください。")
        else:
            try:
                with st.spinner("AI が CAD パラメータを解釈中..."):
                    st.session_state["param_dict"] = generate_cad_json(user_prompt)
            except Exception as e:
                st.error(f"AI 生成エラー: {e}")

    if "param_dict" in st.session_state:
        param_dict = st.session_state["param_dict"]
        st.subheader("📄 生成された CAD パラメータ")
        st.json(param_dict)

# ---------------------------------------------------------
# 3D プレビュー領域 (Three.js 直描画)
# ---------------------------------------------------------
with col_right:
    st.subheader("🖥️ 3D モデル プレビュー")

    if param_dict:
        try:
            result = build_from_dict(param_dict)
            stl_filename = "ai_output.stl"
            export_stl(result.solid, stl_filename)

            st.success(f"生成成功! 体積: {result.volume:.2f} mm³")

            with open(stl_filename, "rb") as f:
                stl_bytes = f.read()
                stl_b64 = base64.b64encode(stl_bytes).decode("utf-8")

            # 修正点: <script src="[URL](URL)"> という壊れたMarkdownリンク記法を
            # 正しい <script src="URL"> に修正した(これが「THREE is not defined」の直接原因だった)。
            html_code = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <style>
                    body {{ margin: 0; overflow: hidden; background-color: #1e1e1e; }}
                    #viewer {{ width: 100vw; height: 400px; }}
                </style>
                <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/build/three.min.js"></script>
                <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
                <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/loaders/STLLoader.js"></script>
            </head>
            <body>
                <div id="viewer"></div>
                <script>
                    function render() {{
                        if (typeof THREE === 'undefined' || typeof THREE.STLLoader === 'undefined') {{
                            setTimeout(render, 100);
                            return;
                        }}

                        try {{
                            const container = document.getElementById('viewer');
                            const scene = new THREE.Scene();
                            scene.background = new THREE.Color(0x1e1e1e);

                            const camera = new THREE.PerspectiveCamera(45, container.clientWidth / 400, 0.1, 1000);
                            camera.position.set(40, 40, 50);

                            const renderer = new THREE.WebGLRenderer({{ antialias: true }});
                            renderer.setSize(container.clientWidth, 400);
                            container.appendChild(renderer.domElement);

                            const controls = new THREE.OrbitControls(camera, renderer.domElement);
                            controls.enableDamping = true;

                            const ambientLight = new THREE.AmbientLight(0xaaaaaa);
                            scene.add(ambientLight);

                            const dirLight1 = new THREE.DirectionalLight(0xffffff, 0.8);
                            dirLight1.position.set(1, 1, 1).normalize();
                            scene.add(dirLight1);

                            const dirLight2 = new THREE.DirectionalLight(0x555555, 0.5);
                            dirLight2.position.set(-1, -1, -1).normalize();
                            scene.add(dirLight2);

                            const gridHelper = new THREE.GridHelper(100, 20, 0x444444, 0x222222);
                            scene.add(gridHelper);

                            const stlData = "{stl_b64}";
                            const binaryString = window.atob(stlData);
                            const len = binaryString.length;
                            const bytes = new Uint8Array(len);
                            for (let i = 0; i < len; i++) {{
                                bytes[i] = binaryString.charCodeAt(i);
                            }}

                            const loader = new THREE.STLLoader();
                            const geometry = loader.parse(bytes.buffer);
                            geometry.center();

                            const material = new THREE.MeshPhongMaterial({{ 
                                color: 0x00a8ff, 
                                specular: 0x111111, 
                                shininess: 200,
                                side: THREE.DoubleSide
                            }});
                            const mesh = new THREE.Mesh(geometry, material);
                            scene.add(mesh);

                            function animate() {{
                                requestAnimationFrame(animate);
                                controls.update();
                                renderer.render(scene, camera);
                            }}
                            animate();
                        }} catch (err) {{
                            document.body.innerHTML = '<div style="color:red; padding:10px;">Render Error: ' + err.message + '</div>';
                        }}
                    }}

                    render();
                </script>
            </body>
            </html>
            """
            components.html(html_code, height=420)

            st.download_button(
                label="📥 STL ファイルをダウンロード",
                data=stl_bytes,
                file_name="ai_model.stl",
                mime="application/octet-stream",
                key="download_stl_btn"
            )

        except Exception as e:
            st.error(f"3D 形状構築エラー: {e}")