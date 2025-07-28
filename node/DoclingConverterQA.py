import os
import re
import json
import tempfile  # 添加缺失的导入
import shutil    # 添加缺失的导入
from collections import defaultdict
import traceback
from pathlib import Path  # 添加缺失的导入

class MarkdownToStructuredQA:
    """Markdown文档转结构化QA格式的转换器 - 表格处理优化版"""
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "markdown_file": ("STRING", {"file_input": True, "label": "Markdown文件"}),
            },
            "optional": {
                "output_path": ("STRING", {"folder_input": True, "label": "输出路径"}),
                "debug": ("BOOLEAN", {"default": True, "label": "调试模式"}),
            }
        }
    
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("json_output", "status")
    FUNCTION = "convert"
    CATEGORY = "RDC/文档处理"
    
    def clean_path(self, path: str) -> str:
        """清理路径字符串，去除多余的引号和空格"""
        cleaned = path.strip().strip('"').strip("'")
        if os.name == 'nt':
            cleaned = cleaned.replace('\\\\', '\\')
        return os.path.normpath(cleaned)

    def convert(self, markdown_file, output_path="", debug=True):
        """主转换函数"""
        try:
            # 清理路径
            markdown_file = self.clean_path(markdown_file)
            output_path = self.clean_path(output_path) if output_path else ""
            
            # 检查文件是否存在
            if not os.path.exists(markdown_file):
                return "", f"错误: 文件不存在 {markdown_file}"
            
            # 读取Markdown内容
            with open(markdown_file, "r", encoding="utf-8") as f:
                markdown_content = f.read()
            
            if debug:
                print(f"成功读取文件: {markdown_file}")
                print(f"文件大小: {len(markdown_content)} 字符")
            
            # 解析Markdown内容
            qa_data = self.parse_markdown(markdown_content, debug)
            
            # 转换为JSON字符串
            json_output = json.dumps(qa_data, ensure_ascii=False, indent=2)
            
            # 保存结果
            save_status = ""
            if output_path:
                save_status = self.save_output(json_output, output_path, markdown_file, debug)
            
            status = f"转换成功! 生成 {len(qa_data)} 个QA项" + save_status
            return json_output, status
        except Exception as e:
            error_msg = f"转换失败: {str(e)}"
            if debug:
                print(f"详细错误信息:\n{traceback.format_exc()}")
            return "", error_msg

    def save_output(self, json_output: str, output_path: str, input_path: str, debug: bool) -> str:
        """保存输出文件"""
        try:
            # 解析输出路径
            resolved_path = self.resolve_output_path(output_path, input_path)
            
            # 确保目录存在
            os.makedirs(os.path.dirname(resolved_path), exist_ok=True)
            
            # 安全写入文件
            self.safe_write_file(resolved_path, json_output)
            
            if debug:
                print(f"已保存到: {resolved_path}")
            return f" | 已保存到: {resolved_path}"
        except Exception as e:
            error_msg = f" | 保存失败: {str(e)}"
            if debug:
                print(f"保存错误: {str(e)}")
            return error_msg
    
    def resolve_output_path(self, output_path: str, input_path: str) -> str:
        """解析输出路径"""
        # 如果是目录，则生成文件名
        if os.path.isdir(output_path):
            input_filename = os.path.basename(input_path)
            output_filename = f"{Path(input_filename).stem}_qa.json"
            return os.path.join(output_path, output_filename)
        
        # 如果没有扩展名，添加.json
        if not Path(output_path).suffix:
            return output_path + ".json"
        
        return output_path
    
    def safe_write_file(self, output_path: str, content: str):
        """安全写入文件"""
        # 使用临时文件
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False) as temp_file:
            temp_file.write(content)
            temp_path = temp_file.name
        
        try:
            # 移动文件到目标位置
            shutil.move(temp_path, output_path)
        finally:
            # 确保临时文件被清理
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except:
                    pass

    def parse_markdown(self, content, debug=False):
        """解析Markdown内容并生成QA格式数据"""
        # 初始化数据结构
        qa_data = []
        current_path = []  # 当前标题路径
        current_key = ""   # 当前关键词
        current_content = []  # 当前内容项
        
        # 按行处理内容
        lines = content.split('\n')
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if not line or line == "---":
                i += 1
                continue  # 跳过空行和分隔线
                
            # 处理标题行
            if match := re.match(r'^(#+)\s+(.*)', line):
                # 保存前一个标题的内容
                if current_key and current_content:
                    qa_data.append({
                        "关键词": [current_key],
                        "回答": current_content
                    })
                    current_content = []
                
                # 更新当前路径
                level = len(match.group(1))
                title = match.group(2).strip()
                
                # 维护当前标题路径
                if level <= len(current_path):
                    current_path = current_path[:level-1]
                current_path.append(title)
                
                # 创建当前关键词
                current_key = "".join(current_path)
                i += 1
                continue
            
            # 处理表格开始
            if re.match(r'^\s*\|', line):
                # 提取表格数据
                table_data, lines_processed = self.extract_table(lines, i)
                if table_data:
                    table_qa = self.process_table(current_key, table_data)
                    qa_data.extend(table_qa)
                    i += lines_processed  # 跳过已处理的表格行
                    continue
            
            # 处理普通内容行
            if current_key:
                # 列表项处理
                if re.match(r'^-\s+', line):
                    current_content.append(line)
                # 其他内容
                else:
                    current_content.append(line)
            
            i += 1
        
        # 处理最后收集的数据
        if current_key and current_content:
            qa_data.append({
                "关键词": [current_key],
                "回答": current_content
            })
        
        return qa_data

    def extract_table(self, lines, start_index):
        """从指定位置开始提取表格数据"""
        table_data = {
            "headers": [],
            "rows": [],
            "note": ""
        }
        
        # 提取表头
        header_line = lines[start_index].strip()
        headers = [h.strip() for h in header_line.split('|')[1:-1] if h.strip()]
        if not headers:
            return None, 1
        
        table_data["headers"] = headers
        
        # 处理后续行
        lines_processed = 1
        row_index = start_index + 1
        
        # 跳过分隔行
        if row_index < len(lines) and re.match(r'^\s*\|?\s*-+\s*\|', lines[row_index]):
            row_index += 1
            lines_processed += 1
        
        # 提取数据行
        while row_index < len(lines):
            line = lines[row_index].strip()
            
            # 表格结束条件
            if not re.match(r'^\s*\|', line):
                # 检查是否有表格注释
                if re.match(r'^>\s*注[:：]', line):
                    table_data["note"] = line.replace("注:", "").replace("注：", "").strip()
                    lines_processed += 1
                break
            
            # 提取行数据
            row_data = [col.strip() for col in line.split('|')[1:-1] if col.strip()]
            if len(row_data) == len(headers):
                table_data["rows"].append(row_data)
            
            row_index += 1
            lines_processed += 1
        
        return table_data, lines_processed

    def process_table(self, base_key, table_data):
        """处理表格数据并生成QA项"""
        qa_items = []
        headers = table_data["headers"]
        note = table_data.get("note", "")
        
        # 为每一行创建QA项
        for row in table_data["rows"]:
            if not row or not headers or len(row) != len(headers):
                continue
                
            # 使用第一列作为行标识
            row_id = row[0]
            
            # 构建行数据字符串
            row_str = ";".join([f"{header}:{value}" for header, value in zip(headers, row)])
            if note:
                row_str += f";注:{note}"
            
            # 构建关键词列表 - 为每一列生成一个关键词
            keywords = []
            for header in headers:
                keywords.append(f"{base_key}{row_id}{header}")
            
            qa_items.append({
                "关键词": keywords,
                "回答": [row_str]
            })
        
        return qa_items

# COMFYUI节点注册
NODE_CLASS_MAPPINGS = {
    "MarkdownToStructuredQA": MarkdownToStructuredQA
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MarkdownToStructuredQA": "MD转JSQA"
}

CATEGORY_MAPPINGS = {
    "RDC/文档处理": "文档处理"
}

def get_custom_categories():
    """获取自定义类别映射"""
    return CATEGORY_MAPPINGS