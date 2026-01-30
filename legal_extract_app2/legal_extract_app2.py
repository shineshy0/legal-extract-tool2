>>> # -*- coding: utf-8 -*-
... """
... 多源异构裁判文书结构化提取工具 - 云端部署版
... 适配：Streamlit Cloud(Linux) + 本地Mac/Windows
... 支持：DOCX/可编辑PDF/图片型PDF/扫描件/JPG/PNG/TXT
... 核心：Tesseract OCR(跨平台) + DeepSeek API + Streamlit可视化 + Excel导出
... 部署：GitHub + Streamlit Cloud | 本地：Mac/Windows直接运行
... """
... import streamlit as st
... import openai
... import json
... import traceback
... from docx import Document
... import pdfplumber
... import pandas as pd
... from pathlib import Path
... import tempfile
... from datetime import datetime
... import pdf2image
... from PIL import Image
... import pytesseract
... import subprocess
... import sys
... 
... # ===== 关键：跨平台适配（本地Mac/Windows + 云端Linux）=====
... def setup_tesseract():
...     """
...     自动检测系统并配置Tesseract：
...     1. 云端Linux：自动安装Tesseract-OCR+中文包，配置路径
...     2. 本地Mac：使用brew安装路径（Intel:/usr/local/ | M1/M2:/opt/homebrew/）
...     3. 本地Windows：需手动安装，默认路径（可自行修改）
...     """
...     try:
...         # 检测系统类型
...         if sys.platform.startswith('linux'):
...             # 云端Streamlit Cloud(Linux)：自动安装系统级Tesseract+中文包
...             subprocess.run(['apt-get', 'update'], check=True, capture_output=True)
            subprocess.run(['apt-get', 'install', '-y', 'tesseract-ocr', 'tesseract-ocr-chi-sim', 'poppler-utils'], check=True, capture_output=True)
            # Linux下Tesseract默认路径
            pytesseract.pytesseract.tesseract_cmd = '/usr/bin/tesseract'
        elif sys.platform.startswith('darwin'):  # Mac OS
            # 自动检测Mac芯片（Intel/M1/M2）
            try:
                subprocess.run(['/opt/homebrew/bin/tesseract', '--version'], check=True, capture_output=True)
                pytesseract.pytesseract.tesseract_cmd = '/opt/homebrew/bin/tesseract'  # M1/M2
            except:
                pytesseract.pytesseract.tesseract_cmd = '/usr/local/bin/tesseract'  # Intel
        elif sys.platform.startswith('win32'):  # Windows（可选适配）
            pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
        # 验证Tesseract是否可用
        pytesseract.get_tesseract_version()
        st.toast("✅ Tesseract OCR环境配置成功（跨平台适配）", icon="🔧")
    except Exception as e:
        st.error(f"❌ Tesseract OCR环境配置失败：{str(e)}")
        st.info("💡 本地运行请先安装Tesseract：Mac(brew install tesseract tesseract-lang) | Windows(官网安装)")
        sys.exit(1)

# 初始化Tesseract（启动时自动执行，跨平台适配）
setup_tesseract()

# ===== 全局配置（可自行修改提取字段）=====
REQUIRED_FIELDS = [
    "文书名称", "案号", "审理法院", "判决日期", "原告/申请人",
    "被告/被申请人", "案由", "诉讼请求", "法院认为", "判决结果", "文书类型"
]
TEXT_CUT_LENGTH = 3000  # 控制API Token消耗
DEEPSEEK_API_BASE = "https://api.deepseek.com/v1"
DEEPSEEK_MODEL = "deepseek-chat"

# ===== Tesseract OCR核心函数（跨平台稳定，无修改）=====
def tesseract_ocr_image(image_path: str) -> str:
    try:
        img = Image.open(image_path)
        # 优化配置：中文+英文，LSTM引擎，单一文本块（适配法律文书）
        ocr_text = pytesseract.image_to_string(
            img,
            lang='chi_sim+eng',
            config='--psm 6 --oem 3'
        )
        return ocr_text.strip() if ocr_text.strip() else "OCR识别失败：图片无有效文本内容"
    except Exception as e:
        raise Exception(f"Tesseract OCR识别异常：{str(e)}")

def tesseract_ocr_scanned_pdf(pdf_path: Path) -> str:
    try:
        # 云端Linux已安装poppler-utils，无需指定路径
        pages = pdf2image.convert_from_path(
            pdf_path.absolute(),
            dpi=300,
            fmt="png",
            poppler_path=None
        )
        full_ocr_content = []
        for page_num, page in enumerate(pages, 1):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp_img:
                page.save(tmp_img.name, format="PNG")
                page_text = tesseract_ocr_image(tmp_img.name)
                full_ocr_content.extend([
                    f"【扫描件PDF-第{page_num}页开始】",
                    page_text,
                    f"【扫描件PDF-第{page_num}页结束】\n"
                ])
                Path(tmp_img.name).unlink(missing_ok=True)
        return "".join(full_ocr_content)
    except Exception as e:
        raise Exception(f"扫描件PDF处理异常：{str(e)}")

# ===== 多格式文本读取函数（跨平台，无修改）=====
def read_docx_file(file_path: Path) -> str:
    try:
        doc = Document(file_path)
        doc_text = [para.text.strip() for para in doc.paragraphs if para.text.strip()]
        return "\n".join(doc_text) if doc_text else "DOCX文件无有效文本内容"
    except Exception as e:
        raise Exception(f"DOCX读取异常：{str(e)}")

def read_pdf_file(file_path: Path) -> str:
    try:
        pdf_text = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    pdf_text.append(page_text.strip())
        return "\n".join(pdf_text) if pdf_text else "PDF无有效文本内容"
    except Exception as e:
        raise Exception(f"可编辑PDF读取异常：{str(e)}")

def read_txt_file(file_path: Path) -> str:
    """跨平台TXT读取，兼容utf-8/gbk，替换原mac专属函数"""
    try:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()
        except:
            with open(file_path, "r", encoding="gbk") as f:
                text = f.read()
        return text.strip() if text else "TXT文件无有效文本内容"
    except Exception as e:
        raise Exception(f"TXT读取异常：{str(e)}")

# ===== 多源异构统一读取入口（跨平台，替换为通用TXT函数）=====
def read_legal_file(file_path: Path) -> str:
    file_suffix = file_path.suffix.lower()
    if file_suffix == ".docx":
        return read_docx_file(file_path)
    elif file_suffix == ".pdf":
        try:
            pdf_text = read_pdf_file(file_path)
            if pdf_text not in ["PDF无有效文本内容", ""]:
                return pdf_text
            else:
                st.warning(f"⚠️ 检测到【{file_path.name}】为图片型PDF（扫描件），启动Tesseract OCR识别...")
                return tesseract_ocr_scanned_pdf(file_path)
        except:
            st.warning(f"⚠️ 检测到【{file_path.name}】为图片型PDF（扫描件），启动Tesseract OCR识别...")
            return tesseract_ocr_scanned_pdf(file_path)
    elif file_suffix in [".jpg", ".jpeg", ".png", "bmp"]:
        st.warning(f"⚠️ 检测到【{file_path.name}】为图片文件，启动Tesseract OCR识别...")
        return tesseract_ocr_image(file_path.absolute())
    elif file_suffix == ".txt":
        return read_txt_file(file_path)  # 通用TXT函数，跨平台
    else:
        raise Exception(f"不支持的文件格式：{file_suffix}，请上传DOCX/PDF/TXT/JPG/PNG")

# ===== DeepSeek API大模型提取（无修改，用户自行输入密钥）=====
def extract_legal_data(text: str, api_key: str) -> dict:
    client = openai.OpenAI(
        api_key=api_key,
        base_url=DEEPSEEK_API_BASE
    )
    extract_fields = "、".join(REQUIRED_FIELDS)
    prompt = f"""
你是资深法官助理，擅长精准提取各类裁判文书的核心法律结构化要素，严格按照要求执行：
1. 必须提取的字段：{extract_fields}
2. 提取硬性规则：
   - 判决日期统一格式为YYYY-MM-DD，无明确时间填「未提及」；
   - 多个原告/被告/案由用顿号「、」分隔，无则填「未提及」；
   - 优先提取案号、审理法院、裁判日期等关键信息，不得遗漏；
   - 诉讼请求、法院认为、判决结果提炼核心内容，无则填「未提及」；
   - 文书类型填写「民事/刑事/行政/其他」，无法判断填「其他」。
3. 输出唯一要求：仅标准JSON格式，无额外文字，字段名严格匹配，空值填「未提及」。

【裁判文书原文（含OCR识别内容）】
{text[:TEXT_CUT_LENGTH]}
    """
    try:
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        legal_dict = json.loads(response.choices[0].message.content.strip())
        # 补全缺失字段，确保Excel表头完整
        for field in REQUIRED_FIELDS:
            if field not in legal_dict or not str(legal_dict[field]).strip():
                legal_dict[field] = "未提及"
        return legal_dict
    except Exception as e:
        raise Exception(f"大模型提取异常：{str(e)}")

# ===== Excel导出（跨平台，桌面路径自动适配）=====
def save_legal_excel(result_list: list) -> str:
    """跨平台Excel导出：云端返回下载链接，本地保存到桌面"""
    try:
        # 转换为DataFrame，调整列顺序
        result_df = pd.DataFrame(result_list)
        col_order = ["文件名", "提取时间"] + REQUIRED_FIELDS
        result_df = result_df[col_order]
        # 生成临时文件（云端/本地都适配）
        time_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        excel_file = f"裁判文书提取结果_{time_stamp}.xlsx"
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_excel:
            result_df.to_excel(tmp_excel.name, index=False, engine="openpyxl")
            # 本地返回路径，云端返回文件对象
            return tmp_excel.name, excel_file
    except Exception as e:
        raise Exception(f"Excel导出异常：{str(e)}")

# ===== Streamlit可视化主界面（优化部署体验，更适合共享）=====
def main():
    st.set_page_config(
        page_title="多源异构裁判文书结构化提取工具",
        page_icon="📜",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    # 页面标题（更适合共享）
    st.title("📜 多源异构裁判文书结构化提取工具")
    st.subheader("✨ 支持DOCX/PDF/扫描件PDF/JPG/PNG/TXT | 批量处理 | Excel一键导出")
    st.markdown("---")
    st.markdown("### 📌 工具说明（云端共享版）")
    st.markdown("1. 基于Tesseract OCR+DeepSeek大模型，跨平台适配（本地/云端）；")
    st.markdown("2. 需自行前往[DeepSeek官网](https://platform.deepseek.com/)获取**免费API Key**；")
    st.markdown("3. 请勿上传涉密文书，API Key仅本地使用，不存储、不上传；")
    st.markdown("4. 支持批量上传多格式文件，自动识别类型并完成OCR+结构化提取。")
    st.markdown("---")

    # 侧边栏：API密钥配置（核心，用户自行输入）
    with st.sidebar:
        st.header("⚙️ API 配置（免费）")
        deepseek_api_key = st.text_input(
            "DeepSeek API Key",
            type="password",
            placeholder="请输入你的DeepSeek免费API Key",
            help="👉 前往 https://platform.deepseek.com/ 注册免费获取，每月额度覆盖300+份"
        )
        st.info(f"✅ 提取字段：{', '.join(REQUIRED_FIELDS)}")
        st.success("💡 提取结果可一键导出Excel，支持数据分析/类案研判")
        st.markdown("---")
        st.caption("📦 部署基于 Streamlit Cloud + GitHub")

    # 主界面：文件批量上传
    st.header("📁 文件上传（支持多格式批量选择）")
    uploaded_files = st.file_uploader(
        "选择裁判文书（可多选）",
        type=["docx", "pdf", "txt", "jpg", "jpeg", "png", "bmp"],
        accept_multiple_files=True,
        help="支持：可编辑PDF/扫描件PDF/Word/图片/纯文本 | 自动识别类型 | 按需OCR"
    )

    # 批量提取按钮（禁用条件：无文件/无API Key）
    extract_btn = st.button("🚀 开始批量结构化提取", type="primary", disabled=not (uploaded_files and deepseek_api_key))
    # 会话状态存储结果，页面刷新不丢失
    if "result_list" not in st.session_state:
        st.session_state.result_list = []

    # 批量处理逻辑
    if extract_btn:
        st.session_state.result_list.clear()
        total_files = len(uploaded_files)
        st.info(f"📊 开始批量处理 → 共{total_files}个文件，正在逐份识别/提取...")
        progress_bar = st.progress(0)
        status_text = st.empty()

        for idx, uploaded_file in enumerate(uploaded_files, 1):
            # 更新进度
            progress = idx / total_files
            progress_bar.progress(progress)
            status_text.text(f"处理中：{idx}/{total_files} → 【{uploaded_file.name}】")

            try:
                # 跨平台临时文件保存
                with tempfile.NamedTemporaryFile(delete=False, suffix=Path(uploaded_file.name).suffix) as tmp_file:
                    tmp_file.write(uploaded_file.getbuffer())
                    tmp_file_path = Path(tmp_file.name)

                # 核心：多源异构文件读取
                file_text = read_legal_file(tmp_file_path)
                # 大模型结构化提取
                legal_data = extract_legal_data(file_text, deepseek_api_key)
                # 补充溯源信息
                legal_data["文件名"] = uploaded_file.name
                legal_data["提取时间"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                st.session_state.result_list.append(legal_data)
                st.success(f"✅ 处理成功：【{uploaded_file.name}】")

            except Exception as e:
                # 异常处理
                error_data = {field: "提取失败" for field in REQUIRED_FIELDS}
                error_data["文件名"] = uploaded_file.name
                error_data["提取时间"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                error_data["文书名称"] = f"失败原因：{str(e)[:50]}..."
                st.session_state.result_list.append(error_data)
                st.error(f"❌ 处理失败：【{uploaded_file.name}】→ {str(e)}")
            finally:
                # 清理临时文件
                if 'tmp_file_path' in locals() and tmp_file_path.exists():
                    tmp_file_path.unlink(missing_ok=True)

        # 处理完成
        progress_bar.progress(100)
        success_count = len([res for res in st.session_state.result_list if res["文书名称"] != "提取失败"])
        status_text.text(f"🎉 批量处理完成！✅成功{success_count}个 | ❌失败{total_files - success_count}个")
        st.balloons()

    # 结果预览 + 跨平台Excel下载（云端关键优化：提供download_button）
    if st.session_state.result_list:
        st.markdown("---")
        st.header("📊 提取结果实时预览")
        result_df = pd.DataFrame(st.session_state.result_list)
        result_df = result_df[["文件名", "提取时间"] + REQUIRED_FIELDS]
        st.dataframe(result_df, use_container_width=True, hide_index=True)

        # Excel下载（云端/本地都适配的Streamlit download_button）
        st.header("📥 标准化Excel结果下载")
        try:
            excel_path, excel_name = save_legal_excel(st.session_state.result_list)
            with open(excel_path, "rb") as f:
                st.download_button(
                    label="💾 一键下载Excel文件",
                    data=f,
                    file_name=excel_name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="secondary"
                )
            # 清理Excel临时文件
            Path(excel_path).unlink(missing_ok=True)
        except Exception as e:
            st.error(f"❌ Excel下载失败：{str(e)}")

# ===== 程序主入口 =====
if __name__ == "__main__":
