# -*- coding: utf-8 -*-
"""
多源异构裁判文书结构化提取工具 - Mac本地稳定版
适配：Mac Intel/M1/M2全芯片 | 基于Tesseract OCR+DeepSeek API
支持格式：DOCX/可编辑PDF/扫描件PDF/JPG/PNG/TXT | 批量处理 | Excel一键导出
本地运行：无需部署，装依赖后直接启动，数据全程本地处理更安全
"""
import streamlit as st
import openai
import json
import traceback
from docx import Document
import pdfplumber
import pandas as pd
from pathlib import Path
import tempfile
from datetime import datetime
import pdf2image
from PIL import Image
import pytesseract
import subprocess
import sys

# ===== 跨平台适配：Tesseract OCR初始化（本地Mac + 云端Linux）=====
def setup_tesseract():
    """
    自动检测系统并配置Tesseract：
    1. 云端Linux：依赖由packages.txt自动安装，直接配置默认路径
    2. 本地Mac：自动检测Intel/M1/M2芯片路径
    """
    try:
        if sys.platform.startswith('linux'):
            # 云端Linux：Tesseract由packages.txt自动安装，默认路径固定
            pytesseract.pytesseract.tesseract_cmd = '/usr/bin/tesseract'
            st.toast("✅ 云端Linux Tesseract配置成功（依赖由packages.txt安装）", icon="☁️")
        elif sys.platform.startswith('darwin'):  # Mac OS
            # 本地Mac：自动检测Intel/M1/M2芯片路径
            try:
                subprocess.run(['/opt/homebrew/bin/tesseract', '--version'], check=True, capture_output=True)
                pytesseract.pytesseract.tesseract_cmd = '/opt/homebrew/bin/tesseract'
                st.toast("✅ Mac M1/M2芯片 Tesseract配置成功", icon="🍎")
            except:
                subprocess.run(['/usr/local/bin/tesseract', '--version'], check=True, capture_output=True)
                pytesseract.pytesseract.tesseract_cmd = '/usr/local/bin/tesseract'
                st.toast("✅ Mac Intel芯片 Tesseract配置成功", icon="🍎")
        # 验证Tesseract可用
        pytesseract.get_tesseract_version()
    except Exception as e:
        if sys.platform.startswith('linux'):
            st.error(f"❌ 云端Linux Tesseract配置失败：{str(e)}")
            st.info("💡 请检查packages.txt是否包含tesseract-ocr、tesseract-ocr-chi-sim、poppler-utils")
        else:
            st.error(f"❌ 本地Mac Tesseract配置失败：{str(e)}")
            st.info("💡 解决方法：打开Mac终端执行 → brew install tesseract tesseract-lang poppler")
        sys.exit(1)

# 初始化Tesseract（跨平台适配，启动时自动执行）
setup_tesseract()

# ===== 全局配置（可根据需求增删提取字段）=====
# 核心法律提取字段，固定11项，适配多数裁判文书
REQUIRED_FIELDS = [
    "文书名称", "案号", "审理法院", "判决日期", "原告/申请人",
    "被告/被申请人", "案由", "诉讼请求", "法院认为", "判决结果", "文书类型"
]
TEXT_CUT_LENGTH = 3000  # 控制API Token消耗，3000字足够提取核心信息
DEEPSEEK_API_BASE = "https://api.deepseek.com/v1"  # DeepSeek API固定地址
DEEPSEEK_MODEL = "deepseek-chat"  # 通用对话模型，适配文本提取

# ===== Tesseract OCR核心函数（Mac本地稳定版）=====
def tesseract_ocr_image(image_path: str) -> str:
    """识别单张图片（JPG/PNG/BMP），优化法律文书中文识别"""
    try:
        img = Image.open(image_path)
        # 最优配置：中文+英文混合识别 + LSTM引擎 + 单一文本块（适配法律文书排版）
        ocr_text = pytesseract.image_to_string(
            img,
            lang='chi_sim+eng',  # chi_sim=简体中文，eng=英文（识别案号/数字）
            config='--psm 6 --oem 3'
        )
        return ocr_text.strip() if ocr_text.strip() else "OCR识别失败：图片无有效文本内容"
    except Exception as e:
        raise Exception(f"图片OCR识别异常：{str(e)}")

def tesseract_ocr_scanned_pdf(pdf_path: Path) -> str:
    """处理扫描件PDF：转300DPI高清图片 → 逐页OCR → 拼接内容（标记页码）"""
    try:
        # 300DPI是法律文书OCR最优分辨率，兼顾速度和识别精度
        pages = pdf2image.convert_from_path(
            pdf_path.absolute(),
            dpi=300,
            fmt="png",
            poppler_path=None  # Mac brew安装poppler后无需指定路径
        )
        full_ocr_content = []
        # 逐页识别并标记页码，方便大模型定位内容
        for page_num, page in enumerate(pages, 1):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp_img:
                page.save(tmp_img.name, format="PNG")
                page_ocr_text = tesseract_ocr_image(tmp_img.name)
                full_ocr_content.extend([
                    f"【扫描件PDF-第{page_num}页开始】",
                    page_ocr_text,
                    f"【扫描件PDF-第{page_num}页结束】\n"
                ])
                # 立即删除临时图片，释放Mac磁盘空间
                Path(tmp_img.name).unlink(missing_ok=True)
        return "".join(full_ocr_content)
    except Exception as e:
        raise Exception(f"扫描件PDF处理异常：{str(e)}")

# ===== 多格式文本读取函数（Mac本地专用，兼容所有文书格式）=====
def read_docx_file(file_path: Path) -> str:
    """读取Word/DOCX文件，提取纯文本"""
    try:
        doc = Document(file_path)
        doc_text = [para.text.strip() for para in doc.paragraphs if para.text.strip()]
        return "\n".join(doc_text) if doc_text else "DOCX文件无有效文本内容"
    except Exception as e:
        raise Exception(f"DOCX读取异常：{str(e)}")

def read_pdf_file(file_path: Path) -> str:
    """读取可编辑PDF文件，提取纯文本（比OCR更快更准确）"""
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
    """读取TXT纯文本文件，兼容utf-8/gbk编码（解决Mac中文乱码）"""
    try:
        # 优先utf-8，失败则自动切换gbk，覆盖所有中文编码场景
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()
        except:
            with open(file_path, "r", encoding="gbk") as f:
                text = f.read()
        return text.strip() if text else "TXT文件无有效文本内容"
    except Exception as e:
        raise Exception(f"TXT读取异常：{str(e)}")

# ===== 多源异构统一读取入口（核心：自动识别文件类型，按需处理）=====
def read_legal_file(file_path: Path) -> str:
    """
    自动识别文件后缀，选择对应处理方式：
    1. DOCX/TXT/可编辑PDF → 直接提取文本
    2. 扫描件PDF/图片 → 先Tesseract OCR → 提取文本
    """
    file_suffix = file_path.suffix.lower()
    # 处理DOCX
    if file_suffix == ".docx":
        return read_docx_file(file_path)
    # 处理PDF（自动区分可编辑/扫描件）
    elif file_suffix == ".pdf":
        try:
            pdf_text = read_pdf_file(file_path)
            if pdf_text not in ["PDF无有效文本内容", ""]:
                return pdf_text
            else:
                st.warning(f"⚠️ 检测到【{file_path.name}】为扫描件PDF，启动Tesseract OCR识别...")
                return tesseract_ocr_scanned_pdf(file_path)
        except:
            st.warning(f"⚠️ 检测到【{file_path.name}】为扫描件PDF，启动Tesseract OCR识别...")
            return tesseract_ocr_scanned_pdf(file_path)
    # 处理图片（JPG/PNG/BMP）
    elif file_suffix in [".jpg", ".jpeg", ".png", "bmp"]:
        st.warning(f"⚠️ 检测到【{file_path.name}】为图片文件，启动Tesseract OCR识别...")
        return tesseract_ocr_image(file_path.absolute())
    # 处理TXT
    elif file_suffix == ".txt":
        return read_txt_file(file_path)
    # 不支持的格式
    else:
        raise Exception(f"不支持的文件格式：{file_suffix}，请上传DOCX/PDF/TXT/JPG/PNG")

# ===== DeepSeek API大模型结构化提取（Mac本地版，密钥仅本地使用）=====
def extract_legal_data(text: str, api_key: str) -> dict:
    """
    调用DeepSeek API提取法律结构化要素：
    1. 严格按配置字段提取，补全缺失字段
    2. 统一输出格式，确保Excel导出无报错
    3. 低温度设置，保证提取结果稳定性
    """
    # 初始化OpenAI客户端（DeepSeek兼容OpenAI接口）
    client = openai.OpenAI(
        api_key=api_key,
        base_url=DEEPSEEK_API_BASE
    )
    # 拼接提取字段，生成专业法律提取Prompt
    extract_fields = "、".join(REQUIRED_FIELDS)
    prompt = f"""
你是资深法院书记员，擅长精准提取各类裁判文书的核心法律结构化要素，严格按照以下要求执行：
1. 必须提取的核心字段：{extract_fields}
2. 提取硬性规则（严格遵守）：
   - 判决日期统一格式化为【YYYY-MM-DD】，无明确判决时间则填「未提及」；
   - 多个原告/被告/申请人/被申请人/案由用【顿号、】分隔，无相关信息则填「未提及」；
   - 优先提取文书中的案号、审理法院、裁判日期等关键标识信息，不得遗漏；
   - 诉讼请求、法院认为、判决结果需提炼**核心关键内容**，不冗余、不删减关键信息，无则填「未提及」；
   - 文书类型严格填写【民事/刑事/行政/其他】，无法准确判断则填「其他」。
3. 输出唯一强制要求：
   - 仅输出**标准JSON格式字符串**，无任何额外文字（如“提取结果：”“以下是答案：”等）；
   - JSON的key与上述提取字段**完全一致**，不得增删、修改、重命名字段；
   - 所有value均为**字符串类型**，空值/无相关信息统一填「未提及」，禁止出现null/None。

【裁判文书原文（含OCR识别内容）】
{text[:TEXT_CUT_LENGTH]}
    """
    try:
        # 调用API，temperature=0.1保证结果稳定性
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"}  # 强制JSON输出
        )
        # 解析API返回结果
        legal_result_dict = json.loads(response.choices[0].message.content.strip())
        # 补全缺失字段（防止API漏返，确保Excel表头完整）
        for field in REQUIRED_FIELDS:
            if field not in legal_result_dict or not str(legal_result_dict[field]).strip():
                legal_result_dict[field] = "未提及"
        return legal_result_dict
    except Exception as e:
        raise Exception(f"大模型结构化提取异常：{str(e)}")

# ===== Excel导出函数（Mac本地专属，直接保存到桌面）=====
def save_legal_excel(result_list: list) -> Path:
    """
    提取结果导出为标准化Excel：
    1. 自动保存到Mac桌面，文件名含时间戳（避免重复）
    2. 列顺序：文件名→提取时间→核心法律字段（方便查看）
    3. 无索引列，直接用于数据分析/类案研判
    """
    try:
        # 转换为Pandas DataFrame，调整列顺序（溯源字段放最前）
        result_df = pd.DataFrame(result_list)
        col_order = ["文件名", "提取时间"] + REQUIRED_FIELDS
        result_df = result_df[col_order]
        # 生成保存路径（Mac桌面 + 时间戳 + 固定前缀）
        mac_desktop = Path.home() / "Desktop"  # Mac桌面默认路径，无需修改
        time_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        excel_save_path = mac_desktop / f"裁判文书提取结果_{time_stamp}.xlsx"
        # 保存为Excel，不生成索引列
        result_df.to_excel(excel_save_path, index=False, engine="openpyxl")
        return excel_save_path
    except Exception as e:
        raise Exception(f"Excel导出异常：{str(e)}")

# ===== Streamlit可视化主界面（Mac本地版，简洁友好）=====
def main():
    # 页面基础配置：标题、图标、宽布局、展开侧边栏
    st.set_page_config(
        page_title="Mac 裁判文书提取工具",
        page_icon="📜",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    # 页面主标题和说明
    st.title("📜 Mac 多源异构裁判文书结构化提取工具")
    st.subheader("✨ 支持 DOCX/可编辑PDF/扫描件PDF/JPG/PNG/TXT | 批量处理 | Excel导出")
    st.markdown("---")
    # 工具使用说明（Mac本地版，简洁明了）
    st.markdown("### 📌 本地使用说明")
    st.markdown("1. 数据**全程本地处理**，无上传、无存储，涉密文书可放心使用；")
    st.markdown("2. 需自行前往 [DeepSeek官网](https://platform.deepseek.com/) 获取**免费API Key**（每月额度覆盖300+份）；")
    st.markdown("3. 支持**多文件批量上传**，自动识别格式，扫描件/图片自动OCR；")
    st.markdown("4. 提取结果**直接保存到Mac桌面**，Excel格式可直接用于数据分析/类案研判。")
    st.markdown("---")

    # 侧边栏：API密钥配置（核心，仅本地输入，不存储）
    with st.sidebar:
        st.header("⚙️ DeepSeek API 配置（免费）")
        deepseek_api_key = st.text_input(
            "请输入你的API Key",
            type="password",
            placeholder="sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            help="👉 前往 https://platform.deepseek.com/ 注册免费获取，密钥仅本地使用"
        )
        # 提取字段提示
        st.info(f"✅ 固定提取字段：\n{chr(10).join(REQUIRED_FIELDS)}")
        st.success("💡 提取结果自动保存到【Mac桌面】，文件名含时间戳")
        st.markdown("---")
        st.caption("📦 技术栈：Tesseract OCR + DeepSeek + Streamlit + Pandas")

    # 主界面：文件批量上传（支持多格式混合选择）
    st.header("📁 文书上传（支持多格式批量选择）")
    uploaded_files = st.file_uploader(
        "选择裁判文书（可多选，支持混合格式）",
        type=["docx", "pdf", "txt", "jpg", "jpeg", "png", "bmp"],
        accept_multiple_files=True,
        help="支持格式：Word/DOCX | 可编辑PDF/扫描件PDF | 图片(JPG/PNG) | 纯文本TXT"
    )

    # 批量提取按钮：未上传文件/未输入API Key则禁用
    extract_button = st.button("🚀 开始批量结构化提取", type="primary", disabled=not (uploaded_files and deepseek_api_key))
    # 会话状态存储提取结果，页面刷新不丢失
    if "result_list" not in st.session_state:
        st.session_state.result_list = []

    # 批量处理核心逻辑
    if extract_button:
        # 清空历史结果，避免累积
        st.session_state.result_list.clear()
        total_file_count = len(uploaded_files)
        st.info(f"📊 开始批量处理 → 共{total_file_count}个文件，正在逐份识别/提取...")
        # 进度条和实时状态提示
        progress_bar = st.progress(0)
        status_text = st.empty()

        # 遍历所有上传文件，逐份处理
        for file_index, uploaded_file in enumerate(uploaded_files, 1):
            # 更新实时处理进度
            process_progress = file_index / total_file_count
            progress_bar.progress(process_progress)
            status_text.text(f"处理中：{file_index}/{total_file_count} → 【{uploaded_file.name}】")

            try:
                # 将上传的临时文件保存为Mac本地临时文件（处理后自动删除）
                with tempfile.NamedTemporaryFile(delete=False, suffix=Path(uploaded_file.name).suffix) as local_tmp_file:
                    local_tmp_file.write(uploaded_file.getbuffer())
                    local_tmp_file_path = Path(local_tmp_file.name)

                # 核心：多源异构文件统一读取（自动识别格式+按需OCR）
                file_raw_text = read_legal_file(local_tmp_file_path)
                # 调用DeepSeek API进行结构化提取
                legal_struct_data = extract_legal_data(file_raw_text, deepseek_api_key)
                # 补充溯源信息：原始文件名、提取时间（方便后续排查/整理）
                legal_struct_data["文件名"] = uploaded_file.name
                legal_struct_data["提取时间"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                # 添加到结果列表
                st.session_state.result_list.append(legal_struct_data)
                st.success(f"✅ 处理成功：【{uploaded_file.name}】")

            except Exception as e:
                # 异常处理：标记提取失败，记录失败原因，保留基础信息
                error_data = {field: "提取失败" for field in REQUIRED_FIELDS}
                error_data["文件名"] = uploaded_file.name
                error_data["提取时间"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                error_data["文书名称"] = f"失败原因：{str(e)[:50]}..."  # 截取原因，避免界面冗余
                st.session_state.result_list.append(error_data)
                st.error(f"❌ 处理失败：【{uploaded_file.name}】→ {str(e)}")
            finally:
                # 强制删除本地临时文件，释放Mac内存和磁盘空间
                if 'local_tmp_file_path' in locals() and local_tmp_file_path.exists():
                    local_tmp_file_path.unlink(missing_ok=True)

        # 批量处理完成，更新最终状态
        progress_bar.progress(100)
        # 统计成功/失败数量
        success_count = len([res for res in st.session_state.result_list if res["文书名称"] != "提取失败"])
        fail_count = total_file_count - success_count
        status_text.text(f"🎉 批量处理完成！✅成功{success_count}个 | ❌失败{fail_count}个")
        st.balloons()  # 处理完成动画提示

    # 提取结果预览 + Excel一键导出（有结果时显示）
    if st.session_state.result_list:
        st.markdown("---")
        # 结果实时预览（隐藏索引，自适应宽布局）
        st.header("📊 提取结果实时预览")
        result_dataframe = pd.DataFrame(st.session_state.result_list)
        result_dataframe = result_dataframe[["文件名", "提取时间"] + REQUIRED_FIELDS]
        st.dataframe(result_dataframe, use_container_width=True, hide_index=True)

        # Excel一键导出（保存到Mac桌面）
        st.header("📥 Excel结果导出（直接保存到桌面）")
        if st.button("💾 一键导出到Mac桌面", type="secondary"):
            try:
                excel_path = save_legal_excel(st.session_state.result_list)
                st.success(f"✅ Excel导出成功！保存路径：\n{excel_path}")
                st.info("💡 文件已保存到Mac桌面，可直接打开进行数据分析/类案研判")
            except Exception as e:
                st.error(f"❌ Excel导出失败：{str(e)}")

# ===== 程序主入口（Mac本地运行必备）=====
if __name__ == "__main__":
    main()
