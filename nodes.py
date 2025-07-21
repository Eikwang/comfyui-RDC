import comfy
import json
import os
import time
import tempfile
import shutil
from pathlib import Path
from typing import Dict, Any, Tuple, Optional, List
import unicodedata
import re
import hashlib

# ---------- 辅助函数 ----------
def zh(label: str, description: str = None) -> Dict[str, str]:
    """为参数添加中文标签和描述"""
    return {"zh_label": label, "zh_description": description or label}

def normalize_filename(filename: str) -> str:
    """规范化文件名，去除特殊字符"""
    return unicodedata.normalize('NFKD', filename).encode('ascii', 'ignore').decode('ascii')

def safe_getattr(obj, attr_name, default=None):
    """安全获取对象属性"""
    return getattr(obj, attr_name, default) if obj else default

def clean_path(path: str) -> str:
    """清理路径字符串，去除多余的引号"""
    # 去除两端的空格和引号
    cleaned = path.strip().strip('"').strip("'")
    
    # 处理Windows路径中的双反斜杠
    if os.name == 'nt':
        # 替换双反斜杠为单反斜杠
        cleaned = cleaned.replace('\\\\', '\\')
        # 处理路径开头可能的多余引号
        if cleaned.startswith('"') or cleaned.startswith("'"):
            cleaned = cleaned[1:]
        if cleaned.endswith('"') or cleaned.endswith("'"):
            cleaned = cleaned[:-1]
    
    cleaned = os.path.normpath(cleaned)
    
    return cleaned

# ---------- 核心转换器 ----------
class DoclingConverter:
    @classmethod
    def INPUT_TYPES(cls) -> Dict[str, Any]:
        return {
            "required": {
                "file_path": ("STRING", {"default": "", "multiline": False, "label": "文件路径", **zh("文件路径", "文档的完整路径或URL")}),
                "format": (["auto", "pdf", "docx", "pptx", "html", "markdown"], 
                          {"default": "auto", "label": "文档格式", **zh("文档格式", "自动检测或指定格式")}),
                "auto_language": ("BOOLEAN", {"default": True, "label": "自动检测语言", **zh("自动检测语言", "启用OCR语言自动检测")}),
                "chunking": ("BOOLEAN", {"default": True, "label": "智能分块", **zh("智能分块", "为RAG优化启用分块处理")}),
                "enhancements": ("BOOLEAN", {"default": True, "label": "增强处理", **zh("增强处理", "启用代码/公式/图片增强")}),
                "enable_cleaning": ("BOOLEAN", {"default": True, "label": "启用数据清洗", **zh("启用数据清洗", "清理和结构化数据")}),
            },
            "optional": {
                "max_pages": ("INT", {"default": 0, "min": 0, "max": 1000, "label": "最大页数", **zh("最大页数", "0=无限制")}),
                "output_path": ("STRING", {"default": "", "label": "保存路径", **zh("保存路径", "将JSON保存到指定路径")}),
                "custom_options": ("JSON", {"default": "{}", "label": "自定义选项", **zh("自定义选项", "JSON格式的高级设置")}),
                "chunk_size": ("INT", {"default": 512, "min": 64, "max": 2048, "label": "分块大小", **zh("分块大小", "字符数/分词数")}),
                "chunk_overlap": ("INT", {"default": 50, "min": 0, "max": 256, "label": "分块重叠", **zh("分块重叠", "块间重叠字符数")}),
                # 新增参数：启用产品ID生成
                "enable_product_id": ("BOOLEAN", {"default": True, "label": "启用产品ID", **zh("启用产品ID", "生成标准化产品标识")}),
                # 新增参数：启用数值索引
                "enable_numerical_index": ("BOOLEAN", {"default": True, "label": "启用数值索引", **zh("启用数值索引", "为数值参数创建索引区间")}),
            }
        }
    
    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("json_output", "status", "metadata")
    FUNCTION = "convert"
    CATEGORY = "Docling/文档处理"
    OUTPUT_NODE = True

    def convert(self, **kwargs) -> Tuple[str, str, str]:
        """执行文档转换"""
        start_time = time.time()  # 记录开始时间
        try:
            # 提取参数并清理路径
            file_path = clean_path(kwargs.get("file_path", ""))
            output_path = clean_path(kwargs.get("output_path", ""))
            
            # 验证文件存在
            if not self.validate_file(file_path):
                return self.error_response(f"文件不存在: {file_path}")
            
            # 准备转换
            converter, format = self.prepare_converter(kwargs, file_path)
            
            # 执行转换
            result = self.perform_conversion(converter, file_path)
            
            # 处理结果
            json_output, metadata = self.process_result(result, kwargs, start_time)
            
            # 保存文件
            save_status = self.save_output(json_output, output_path, file_path)
            
            return (json_output, f"成功{save_status}", metadata)
        except Exception as e:
            return self.error_response(f"转换失败: {str(e)}") 

    def validate_file(self, file_path: str) -> bool:
        """验证文件是否存在"""
        return os.path.exists(file_path)    
    
    def prepare_converter(self, params: Dict[str, Any], file_path: str):
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.datamodel.base_models import InputFormat
        
        # 创建流水线选项
        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = True
        pipeline_options.ocr_options.lang = ["auto"] if params.get("auto_language") else ["en"]
        pipeline_options.do_table_structure = True
        pipeline_options.generate_page_images = True
        pipeline_options.do_code_enrichment = params.get("enhancements", True)
        pipeline_options.do_formula_enrichment = params.get("enhancements", True)
        pipeline_options.do_picture_classification = params.get("enhancements", True)
        
        # 添加自定义选项
        if custom_options := params.get("custom_options"):
            custom_options = json.loads(custom_options)
            for key, value in custom_options.items():
                setattr(pipeline_options, key, value)
        
        # 创建转换器
        from docling.document_converter import DocumentConverter, PdfFormatOption
        return (
            DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
                }
            ),
            "pdf"
        )

    def validate_tesseract(self):
        if "TESSDATA_PREFIX" not in os.environ:
            raise EnvironmentError("TESSDATA_PREFIX environment variable not set. Refer to Docling Tesseract installation docs")
        if not shutil.which("tesseract"):
            raise FileNotFoundError("Tesseract not found in system PATH")

    def perform_conversion(self, converter, file_path: str):
        """执行文档转换"""
        return converter.convert(source=file_path)

    def process_result(self, result, params: Dict[str, Any], start_time: float) -> Tuple[str, str]:
        if params.get("chunking", True):
            return self.process_chunks(result.document, params, start_time)
        else:
            return self.process_full_doc(result.document, params, start_time)

    def process_chunks(self, doc, params: Dict[str, Any], start_time: float) -> Tuple[str, str]:
        """处理分块结果 - 通用优化"""
        from docling.chunking import HybridChunker
        chunker = HybridChunker(
            tokenizer="BAAI/bge-small-en-v1.5",
            chunk_size=params.get("chunk_size", 512),
            overlap=params.get("chunk_overlap", 50),
            merge_peers=True
        )
        chunks = list(chunker.chunk(doc))
        
        if len(chunks) > 100:
            print(f"处理中: 共{len(chunks)}个分块...")
        
        # 构建分块JSON
        chunk_data = []
        for chunk in chunks:
            # 提取元数据
            chunk_meta = self.extract_chunk_metadata(chunk, params)
            
            # 获取原始文本和元数据
            original_text = safe_getattr(chunk, 'text', '')
            original_meta = chunk_meta
            
            # 检查是否启用优化
            if params.get("enable_cleaning", True):
                # 先进行基础清洗
                cleaned_text, cleaned_meta = self.restructure_chunk_data(
                    original_text, 
                    original_meta,
                    params
                )
                
                # 如果需要额外重构
                if params.get("enable_restructuring", True):
                    cleaned_text, cleaned_meta = self.restructure_chunk_data(
                        cleaned_text, 
                        cleaned_meta,
                        params
                    )
            else:
                cleaned_text = original_text
                cleaned_meta = original_meta
            
            # 移除空字段
            cleaned_meta = self.remove_empty_fields(cleaned_meta)
            
            chunk_data.append({
                "text": cleaned_text,
                "metadata": cleaned_meta
            })
        
        # 生成输出
        json_output = json.dumps(chunk_data, indent=2, ensure_ascii=False)
        metadata = json.dumps({
            "chunk_count": len(chunk_data),
            "page_count": len(doc.pages) if hasattr(doc, 'pages') else 0,
            "optimizations_applied": params.get("enable_cleaning", True)
        }, ensure_ascii=False)
        
        return json_output, metadata
    
    def restructure_chunk_data(self, text: str, metadata: Dict, params: Dict[str, Any]) -> Tuple[str, Dict]:
        """重构分块数据结构 - 基于层级提取"""
        
        # 2. 添加关键词
        if "keywords" not in metadata:
            metadata["keywords"] = self.extract_keywords(text)
        
        # 3. 添加最后更新时间戳
        metadata["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        
        # 4. 生成产品ID（如果启用）
        if params.get("enable_product_id", True):
            metadata["product_id"] = self.generate_product_id(
                metadata.get("section", []),
                text
            )
        
        # 5. 提取数值参数（如果启用）
        if params.get("enable_numerical_index", True):
            numerical_params = self.extract_numerical_params(text)
            if numerical_params:
                metadata["numerical_params"] = numerical_params
        
        # 6. 提取促销活动信息
        promotion_info = self.extract_promotion_info(text)
        if promotion_info:
            metadata["promotion"] = promotion_info
        
        # 7. 提取注意事项
        warnings = self.extract_warnings(text)
        if warnings:
            metadata["warnings"] = warnings
        
        # 8. 提取适用场景
        applicable_scenes = self.extract_applicable_scenes(text)
        if applicable_scenes:
            metadata["applicable_scenes"] = applicable_scenes
        
        return text, metadata
    
    def extract_promotion_info(self, text: str) -> List[str]:
        """提取促销活动信息"""
        promotions = []
        
        # 匹配促销关键词
        promotion_patterns = [
            r'优惠活动[:：]?\s*([^\n]+)',
            r'促销[:：]?\s*([^\n]+)',
            r'满(\d+)[件箱个包套]赠',
            r'购买(.+?)满(\d+)[件箱个包套]'
        ]
        
        for pattern in promotion_patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                if isinstance(match, tuple):
                    # 处理多个捕获组的情况
                    promotion = " ".join([m for m in match if m])
                else:
                    promotion = match
                
                if promotion and promotion not in promotions:
                    promotions.append(promotion)
        
        return promotions
    
    def extract_warnings(self, text: str) -> List[str]:
        """提取注意事项"""
        warnings = []
        
        # 匹配注意事项关键词
        warning_patterns = [
            r'注意[:：]?\s*([^\n]+)',
            r'警告[:：]?\s*([^\n]+)',
            r'禁忌[:：]?\s*([^\n]+)',
            r'避免([^\n]+)',
            r'请勿([^\n]+)',
            r'不应([^\n]+)',
            r'不要([^\n]+)',
            r'不适合([^\n]+)'
        ]
        
        for pattern in warning_patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                if match and match not in warnings:
                    warnings.append(match)
        
        return warnings
    
    def extract_applicable_scenes(self, text: str) -> List[str]:
        """提取适用场景"""
        scenes = []
        
        # 匹配适用场景关键词
        scene_patterns = [
            r'(?:适用(?:于|场景)|适合(?:于|场景)|用于|应用(?:于|场景)|场合)[:：]?\s*([^\n]+)'
        ]
        
        # 场景化标签提取
        scene_keywords = [
            "家庭", "公司", "办公室", "商务酒店", "高档餐厅", "机场", "公园", "公共场所",
            "日料店", "酒楼", "海鲜店", "厨房", "浴室", "家私", "环境消毒", "物体表面",
            "餐饮具", "衣物", "纺织品"
        ]
        
        # 处理正则匹配的场景描述
        for pattern in scene_patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                if not match:
                    continue
                    
                # 分割复合场景
                split_scenes = re.split(r'[、,，;；\s和及与]', match)
                for scene in split_scenes:
                    # 清洗场景字符串
                    scene = scene.strip().rstrip('.,:;。，：；')
                    if scene and scene not in scenes:
                        scenes.append(scene)
        
        # 高效提取场景关键词
        keyword_pattern = r'\b(' + '|'.join(re.escape(kw) for kw in scene_keywords) + r')\b'
        scene_tags = list(set(re.findall(keyword_pattern, text)))
        
        # 合并结果并去重
        all_scenes = list(set(scenes + scene_tags))
        return all_scenes
    
    def __init__(self):
        # 可配置的特征提取器
        self.feature_extractors = [
            self.extract_key_value_pairs,
            self.extract_numerical_features,
            self.extract_entity_nouns,
            self.extract_special_features
        ]
        
        # 特征权重配置（可扩展）
        self.feature_weights = {
            "品牌": 10,
            "型号": 9,
            "材质": 8,
            "尺寸": 7,
            "容量": 7,
            "重量": 6,
            "颜色": 5,
            "适用场景": 4,
            "价格": 3
        }

    def generate_product_id(self, section_hierarchy: List[str], text: str) -> str:
        """生成通用产品ID - 基于文档结构和内容特征"""
        # 1. 构建层级标识
        hierarchy_id = self.generate_hierarchy_id(section_hierarchy)
        
        # 2. 提取关键特征
        feature_hash = self.extract_content_features(text)
        
        # 3. 组合ID
        return f"{hierarchy_id}_{feature_hash}"

    def generate_hierarchy_id(self, section_hierarchy: List[str]) -> str:
        """基于文档层级生成标识"""
        # 使用最后两级标题作为基础
        if len(section_hierarchy) >= 2:
            # 取最后两级标题
            last_two = section_hierarchy[-2:]
            # 规范化标题文本
            normalized = [self.normalize_title(title) for title in last_two]
            return "_".join(normalized)
        
        # 如果层级不足，使用所有层级
        return "_".join([self.normalize_title(title) for title in section_hierarchy])

    def normalize_title(self, title: str) -> str:
        """规范化标题文本"""
        # 移除特殊字符和空格
        cleaned = re.sub(r'[^\w\u4e00-\u9fa5]', '', title)
        # 限制长度
        return cleaned[:20] if len(cleaned) > 20 else cleaned

    def extract_content_features(self, text: str) -> str:
        """提取文本内容特征并生成哈希"""
        # 1. 提取所有特征
        all_features = self.extract_all_features(text)
        
        # 2. 生成特征签名
        feature_signature = self.generate_feature_signature(all_features)
        
        # 3. 生成短哈希
        return self.generate_short_hash(feature_signature)

    def extract_all_features(self, text: str) -> Dict[str, List[str]]:
        """提取所有类型的特征"""
        features = {}
        
        # 使用所有注册的特征提取器
        for extractor in self.feature_extractors:
            feature_type = extractor.__name__.replace("extract_", "")
            result = extractor(text)
            
            if result:
                features[feature_type] = result
        
        return features

    def generate_feature_signature(self, features: Dict[str, List[str]]) -> str:
        """生成特征签名字符串"""
        # 按权重排序特征
        sorted_features = []
        for feature_type, values in features.items():
            # 计算特征类型权重
            weight = self.feature_weights.get(feature_type, 1)
            sorted_features.append((feature_type, values, weight))
        
        # 按权重降序排序
        sorted_features.sort(key=lambda x: x[2], reverse=True)
        
        # 构建签名字符串
        signature_parts = []
        for feature_type, values, _ in sorted_features:
            # 对值进行排序以确保一致性
            sorted_values = sorted(values)
            signature_parts.append(f"{feature_type}:{'|'.join(sorted_values)}")
        
        return "#".join(signature_parts)

    def extract_key_value_pairs(self, text: str) -> List[str]:
        """提取键值对特征"""
        # 匹配键值对模式
        pattern = r'([\u4e00-\u9fa5a-zA-Z]{2,10})[:：]\s*([^\n]+?)(?=[\n、,，;；]|$)'
        matches = re.findall(pattern, text)
        
        # 过滤和处理键值对
        key_value_pairs = []
        for key, value in matches:
            # 规范化键名
            normalized_key = self.normalize_feature_key(key)
            
            # 清理值
            cleaned_value = value.strip().rstrip('.,:;。，：；')
            
            # 跳过空值或无效键
            if not cleaned_value or not normalized_key:
                continue
            
            # 添加键值对
            key_value_pairs.append(f"{normalized_key}={cleaned_value}")
        
        return key_value_pairs

    def normalize_feature_key(self, key: str) -> str:
        """规范化特征键名"""
        # 常见键名映射
        key_mapping = {
            "规格": "型号",
            "规格型号": "型号",
            "净含量": "容量",
            "重量": "净重",
            "尺寸": "规格尺寸",
            "适用": "适用场景",
            "用途": "适用场景",
            "场景": "适用场景",
            "品牌": "品牌",
            "材质": "材质",
            "颜色": "颜色",
            "售价": "价格",
            "价格": "价格",
            "原价": "价格",
            "特价": "特价",
            "优惠价": "特价",
            "活动价": "特价",
            "直播间售价": "特价"
        }
        
        # 返回映射值或原键名
        return key_mapping.get(key, key)

    def extract_numerical_features(self, text: str) -> List[str]:
        """提取数值特征"""
        # 匹配数值描述
        pattern = r'([\u4e00-\u9fa5a-zA-Z]{1,8})[:：]?\s*(\d+(?:\.\d+)?)([a-zA-Z%]{1,4})?'
        matches = re.findall(pattern, text)
        
        features = []
        for key, value, unit in matches:
            # 规范化键名
            normalized_key = self.normalize_feature_key(key)
            
            # 跳过常见非特征键
            if normalized_key in ["编号", "页码", "序号", "代码"]:
                continue
            
            # 格式化数值特征
            feature = f"{normalized_key}:{value}"
            if unit:
                feature += unit
            features.append(feature)
        
        return features

    def extract_entity_nouns(self, text: str) -> List[str]:
        """提取实体名词特征"""
        # 匹配名词短语
        pattern = r'([\u4e00-\u9fa5]{2,8}的)?[\u4e00-\u9fa5]{2,10}'
        matches = re.findall(pattern, text)
        
        # 过滤常见虚词
        stopwords = {"的", "是", "在", "和", "有", "了", "就", "也", "要", "与", "或", "等", "及", "或", "且"}
        entities = []
        
        for entity in matches:
            # 清理实体
            entity = entity.strip()
            
            # 跳过短实体和虚词
            if len(entity) < 2 or entity in stopwords:
                continue
            
            # 跳过重复实体
            if entity not in entities:
                entities.append(entity)
        
        return entities

    def extract_special_features(self, text: str) -> List[str]:
        """提取特殊特征（优惠、功能等）"""
        special_features = []
        
        # 匹配特殊特征模式
        patterns = [
            r'(优惠|活动|促销)[:：]?\s*([^\n]+)',
            r'(功能|特点|卖点)[:：]?\s*([^\n]+)',
            r'(注意事项|警告|特价)[:：]?\s*([^\n]+)'
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text)
            for feature_type, value in matches:
                # 清理值
                cleaned_value = value.strip().rstrip('.,:;。，：；')
                if cleaned_value:
                    special_features.append(f"{feature_type}:{cleaned_value}")
        
        return special_features

    def generate_short_hash(self, text: str, length: int = 8) -> str:
        """生成短哈希"""
        # 创建SHA256哈希
        hash_obj = hashlib.sha256(text.encode('utf-8'))
        full_hash = hash_obj.hexdigest()
        
        # 返回指定长度的短哈希
        return full_hash[:length]
    
    def extract_keywords(self, text: str) -> List[str]:
        """从文本中提取关键词（优化版）"""
        # 停用词列表
        stopwords = {"的", "是", "在", "和", "有", "了", "就", "也", "要", "与", "或", "等"}
        
        keywords = []
        
        # 提取完整名词短语（避免截断）
        noun_phrases = re.findall(r'[\u4e00-\u9fa5]{2,8}(?:的)?[\u4e00-\u9fa5]{2,8}', text)
        keywords.extend([phrase for phrase in noun_phrases if not any(sw in phrase for sw in stopwords)])
        
        # 提取特定术语（业务强相关词）
        business_terms = re.findall(
            r'免打孔安装|99%氯含量|[\u4e00-\u9fa5]{2,6}剂|[\u4e00-\u9fa5]{2,6}液|[\u4e00-\u9fa5]{2,6}盒|[\u4e00-\u9fa5]{2,6}机', 
            text
        )
        keywords.extend(business_terms)
        
        # 提取完整短语（避免截断）
        full_phrases = re.findall(r'[\u4e00-\u9fa5]{4,12}', text)
        keywords.extend([phrase for phrase in full_phrases if len(phrase) > 3 and not any(sw in phrase for sw in stopwords)])
        
        # 去重并返回
        return list(set(keywords))
    
    def extract_numerical_params(self, text: str) -> Dict[str, Any]:
        """提取数值型参数并建立索引区间"""
        params = {}
        
        # 提取尺寸参数
        size_matches = re.findall(r'(长|宽|高|尺寸|体积|容量|直径)[:：]?\s*(\d+)(mm|cm|m|L|ml)?', text)
        for dim, value, unit in size_matches:
            dim_key = f"size_{dim}"
            params[dim_key] = {
                "value": int(value),
                "unit": unit if unit else "mm",
                "range": [int(value)-5, int(value)+5]  # ±5的区间
            }
        
        # 提取数量参数
        quantity_match = re.search(r'(数量|层数|张数|抽数)[:：]?\s*(\d+)(个|张|层|抽|支)?', text)
        if quantity_match:
            qty = int(quantity_match.group(2))
            params["quantity"] = {
                "value": qty,
                "range": [max(0, qty-10), qty+10] 
            }
        
        # 提取重量参数
        weight_match = re.search(r'(净含量|重量|厚度)[:：]?\s*(\d+)(g|kg|丝|)?', text)
        if weight_match:
            weight = int(weight_match.group(2))
            unit = weight_match.group(3) if weight_match.group(3) else "g"
            params["weight"] = {
                "value": weight,
                "unit": unit,
                "range": [max(0, weight-50), weight+50]  # ±50的区间
            }
        
        return params
    
    def extract_chunk_metadata(self, chunk, params: Dict[str, Any]) -> Dict[str, Any]:
        """提取分块元数据 - 整合优化逻辑"""
        # 安全获取属性
        meta = chunk.meta
        headings = safe_getattr(meta, 'headings', [])
        item_type = safe_getattr(meta, 'item_type', '未知')
        
        # 图注处理
        figure_captions = []
        if hasattr(meta, 'figure_captions'):
            for cap in meta.figure_captions:
                figure_captions.append(safe_getattr(cap, 'text', ''))
        
        # 图片元数据
        images_list = []
        if hasattr(meta, 'pictures') and meta.pictures:
            for pic in meta.pictures:
                bbox = safe_getattr(pic, 'bbox', None)
                position = [
                    safe_getattr(bbox, 'l', 0) if bbox else 0,
                    safe_getattr(bbox, 't', 0) if bbox else 0,
                    safe_getattr(bbox, 'r', 0) if bbox else 0,
                    safe_getattr(bbox, 'b', 0) if bbox else 0
                ]
                
                images_list.append({
                    "id": safe_getattr(pic, 'id', ''),
                    "description": safe_getattr(pic, 'description', ''),
                    "position": position
                })
        
        # 构建元数据
        metadata = {
            "section": safe_getattr(meta, 'headings', []),
            "item_type": safe_getattr(meta, 'item_type', 'text'),
            "tables": [t.export_to_dict() for t in safe_getattr(meta, 'tables', [])],
            "images": images_list  # 直接使用定义好的列表
        }
        
        # 处理多级规格
        if "规格型号" in headings and item_type == "specification":
            metadata["specifications"] = self.extract_specifications(chunk.text)
        
        # 保留非空字段
        if figure_captions:
            metadata["figure_captions"] = figure_captions
        
        return metadata
    
    def extract_specifications(self, text: str) -> List[Dict]:
        """从文本中提取规格信息（嵌套结构）"""
        specifications = []
        
        # 使用正则表达式匹配规格项
        spec_items = re.split(r'\n\s*-\s*', text)
        
        for item in spec_items:
            if not item.strip():
                continue
                
            # 提取规格属性
            spec_data = {}
            lines = item.split('\n')
            for line in lines:
                if ':' in line or '：' in line:
                    key, value = re.split(r'[:：]', line, 1)
                    spec_data[key.strip()] = value.strip()
                elif line.strip():
                    # 如果没有分隔符，可能是规格名称
                    if "name" not in spec_data:
                        spec_data["name"] = line.strip()
            
            if spec_data:
                specifications.append(spec_data)
        
        return specifications
    
    def clean_text(self, text: str) -> str:
        """通用文本清洗（优化版）"""
        # 将\n转换为列表结构
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        # 移除尾部标点
        cleaned_lines = []
        for line in lines:
            # 移除行尾标点
            line = re.sub(r'[，,。、；;]+$', '', line)
            cleaned_lines.append(line)
        
        # 返回清洗后的文本（保留换行符）
        return '\n'.join(cleaned_lines)
    
    def clean_metadata(self, metadata: Dict) -> Dict:
        """通用元数据清洗"""
        # 移除空字段
        for field in ["figure_captions", "images"]:
            if field in metadata and not metadata[field]:
                del metadata[field]
        
        # 填充空字段
        if "page" in metadata and not metadata["page"]:
            metadata["page"] = "未知"
        
        return metadata
    
    def remove_empty_fields(self, metadata: Dict) -> Dict:
        """移除空字段"""
        # 移除空列表和空字符串
        for key in list(metadata.keys()):
            if metadata[key] in (None, "", [], {}):
                del metadata[key]
        return metadata
    
    def process_full_doc(self, doc, params: Dict[str, Any], start_time: float) -> Tuple[str, str]:
        """处理完整文档"""
        doc_dict = doc.export_to_dict()
        doc_dict["metadata"] = {
            "source_file": params.get("file_path", "未知"),  # 使用 get 方法
            "format": params.get("format", "未知"),
            "processing_time": time.time() - start_time,
            "last_updated": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        }
        
        json_output = json.dumps(doc_dict, indent=2, ensure_ascii=False)
        metadata = json.dumps({
            "text_item_count": len(doc_dict.get("texts", [])),
            "table_count": len(doc_dict.get("tables", [])),
            "image_count": len(doc_dict.get("pictures", [])),
            "page_count": len(doc.pages) if hasattr(doc, 'pages') else 0
        }, ensure_ascii=False)
        
        return json_output, metadata
    
    def save_output(self, json_output: str, output_path: str, input_path: str) -> str:
        """保存输出文件"""
        if not output_path:
            return ""
        
        try:
            # 解析输出路径
            resolved_path = self.resolve_output_path(output_path, input_path)
            
            # 确保目录存在
            os.makedirs(os.path.dirname(resolved_path), exist_ok=True)
            
            # 安全写入文件
            self.safe_write_file(resolved_path, json_output)
            
            return " | 已保存"
        except Exception as e:
            return f" | 保存失败: {str(e)}"
    
    def resolve_output_path(self, output_path: str, input_path: str) -> str:
        """解析输出路径"""
        # 如果是目录，则生成文件名
        if os.path.isdir(output_path):
            input_filename = os.path.basename(input_path)
            output_filename = f"{Path(input_filename).stem}.json"
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
                os.remove(temp_path)
    
    def error_response(self, message: str) -> Tuple[str, str, str]:
        """生成错误响应"""
        return (
            json.dumps({"error": message}, ensure_ascii=False),
            "失败",
            json.dumps({"error": message}, ensure_ascii=False)
        )

# ---------- 元数据提取器 ----------
class DoclingMetadataExtractor:
    """元数据提取器 - 从JSON中提取特定内容"""
    
    @classmethod
    def INPUT_TYPES(cls) -> Dict[str, Any]:
        # 定义选项列表（使用简单的字符串列表）
        extract_options = ["all_metadata", "text_only", "tables", "images", "product_ids", "numerical_params",
                          "promotions", "warnings", "applicable_scenes"]
        
        return {
            "required": {
                "json_input": ("STRING", {"default": "", "multiline": True, "label": "JSON输入", **zh("JSON输入", "Docling生成的JSON数据")}),
                "extract_type": (extract_options, {"default": "all_metadata", "label": "提取类型", **zh("提取类型", "选择要提取的内容类型")}),
            }
        }
    
    RETURN_TYPES = ("STRING", "STRING", "LIST") 
    RETURN_NAMES = ("text_output", "metadata", "items")
    FUNCTION = "extract"
    CATEGORY = "Docling/文档处理"

    def extract(self, json_input: str, extract_type: str) -> Tuple[str, str, list]:
        try:
            data = json.loads(json_input)
            
            # 处理分块JSON
            if isinstance(data, list):
                return self.handle_chunked_data(data, extract_type)
            
            # 处理完整文档JSON
            return self.handle_full_document(data, extract_type)
                    
        except Exception as e:
            return (
                json.dumps({"error": str(e)}, ensure_ascii=False),
                "失败",
                []
            )
    
    def handle_chunked_data(self, data: List[Dict], extract_type: str) -> Tuple[str, str, list]:
        """处理分块数据"""
        if extract_type == "text_only":
            texts = [item["text"] for item in data]
            return ("\n\n".join(texts), json.dumps({"item_count": len(texts)}), texts)
        
        elif extract_type == "tables":
            tables = [item for item in data if "table" in item.get("item_type", "")]
            return (json.dumps(tables), json.dumps({"table_count": len(tables)}), tables)
        
        elif extract_type == "images":
            images = []
            for item in data:
                if "images" in item.get("metadata", {}):
                    images.extend(item["metadata"]["images"])
            return (json.dumps(images), json.dumps({"image_count": len(images)}), images)
        
        elif extract_type == "product_ids":
            product_ids = []
            for item in data:
                metadata = item.get("metadata", {})
                if "product_id" in metadata:
                    product_ids.append({
                        "product_id": metadata["product_id"],
                        "text": item["text"][:100] + "..." if len(item["text"]) > 100 else item["text"]
                    })
            return (json.dumps(product_ids), json.dumps({"product_id_count": len(product_ids)}), product_ids)
        
        elif extract_type == "numerical_params":
            numerical_params = []
            for item in data:
                metadata = item.get("metadata", {})
                if "numerical_params" in metadata:
                    numerical_params.append({
                        "numerical_params": metadata["numerical_params"],
                        "text": item["text"][:100] + "..." if len(item["text"]) > 100 else item["text"]
                    })
            return (json.dumps(numerical_params), json.dumps({"numerical_param_count": len(numerical_params)}), numerical_params)
        
        elif extract_type == "promotions":
            promotions = []
            for item in data:
                metadata = item.get("metadata", {})
                if "promotion" in metadata:
                    for promo in metadata["promotion"]:
                        promotions.append({
                            "promotion": promo,
                            "text": item["text"][:100] + "..." if len(item["text"]) > 100 else item["text"]
                        })
            return (json.dumps(promotions), json.dumps({"promotion_count": len(promotions)}), promotions)
        
        elif extract_type == "warnings":
            warnings = []
            for item in data:
                metadata = item.get("metadata", {})
                if "warnings" in metadata:
                    for warning in metadata["warnings"]:
                        warnings.append({
                            "warning": warning,
                            "text": item["text"][:100] + "..." if len(item["text"]) > 100 else item["text"]
                        })
            return (json.dumps(warnings), json.dumps({"warning_count": len(warnings)}), warnings)
        
        elif extract_type == "applicable_scenes":
            scenes = []
            for item in data:
                metadata = item.get("metadata", {})
                if "applicable_scenes" in metadata:
                    for scene in metadata["applicable_scenes"]:
                        scenes.append({
                            "scene": scene,
                            "text": item["text"][:100] + "..." if len(item["text"]) > 100 else item["text"]
                        })
            return (json.dumps(scenes), json.dumps({"scene_count": len(scenes)}), scenes)
        
        else:  # all_metadata
            return (json.dumps(data), json.dumps({"chunk_count": len(data)}), data)
    
    def handle_full_document(self, data: Dict, extract_type: str) -> Tuple[str, str, list]:
        """处理完整文档"""
        if extract_type == "text_only":
            texts = [text_item["text"] for text_item in data.get("texts", [])]
            return ("\n\n".join(texts), json.dumps({"text_count": len(texts)}), texts)
        
        elif extract_type == "tables":
            tables = data.get("tables", [])
            return (json.dumps(tables), json.dumps({"table_count": len(tables)}), tables)
        
        elif extract_type == "images":
            images = data.get("pictures", [])
            return (json.dumps(images), json.dumps({"image_count": len(images)}), images)
        
        elif extract_type == "product_ids":
            product_ids = []
            for text_item in data.get("texts", []):
                if "product_id" in text_item.get("metadata", {}):
                    product_ids.append({
                        "product_id": text_item["metadata"]["product_id"],
                        "text": text_item["text"][:100] + "..." if len(text_item["text"]) > 100 else text_item["text"]
                    })
            return (json.dumps(product_ids), json.dumps({"product_id_count": len(product_ids)}), product_ids)
        
        elif extract_type == "numerical_params":
            numerical_params = []
            for text_item in data.get("texts", []):
                if "numerical_params" in text_item.get("metadata", {}):
                    numerical_params.append({
                        "numerical_params": text_item["metadata"]["numerical_params"],
                        "text": text_item["text"][:100] + "..." if len(text_item["text"]) > 100 else text_item["text"]
                    })
            return (json.dumps(numerical_params), json.dumps({"numerical_param_count": len(numerical_params)}), numerical_params)
        
        elif extract_type == "promotions":
            promotions = []
            for text_item in data.get("texts", []):
                metadata = text_item.get("metadata", {})
                if "promotion" in metadata:
                    for promo in metadata["promotion"]:
                        promotions.append({
                            "promotion": promo,
                            "text": text_item["text"][:100] + "..." if len(text_item["text"]) > 100 else text_item["text"]
                        })
            return (json.dumps(promotions), json.dumps({"promotion_count": len(promotions)}), promotions)
        
        elif extract_type == "warnings":
            warnings = []
            for text_item in data.get("texts", []):
                metadata = text_item.get("metadata", {})
                if "warnings" in metadata:
                    for warning in metadata["warnings"]:
                        warnings.append({
                            "warning": warning,
                            "text": text_item["text"][:100] + "..." if len(text_item["text"]) > 100 else text_item["text"]
                        })
            return (json.dumps(warnings), json.dumps({"warning_count": len(warnings)}), warnings)
        
        elif extract_type == "applicable_scenes":
            scenes = []
            for text_item in data.get("texts", []):
                metadata = text_item.get("metadata", {})
                if "applicable_scenes" in metadata:
                    for scene in metadata["applicable_scenes"]:
                        scenes.append({
                            "scene": scene,
                            "text": text_item["text"][:100] + "..." if len(text_item["text"]) > 100 else text_item["text"]
                        })
            return (json.dumps(scenes), json.dumps({"scene_count": len(scenes)}), scenes)
        
        else:  # all_metadata
            return (json.dumps(data, ensure_ascii=False), json.dumps({"document_type": "full"}), [data])

# ---------- 批量处理器 ----------
class DoclingBatchProcessor:
    """批量处理器 - 处理整个文件夹的文档"""
    
    @classmethod
    def INPUT_TYPES(cls) -> Dict[str, Any]:
        return {
            "required": {
                "folder_path": ("STRING", {"default": "", "label": "文件夹路径", **zh("文件夹路径", "包含文档的文件夹路径")}),
                "output_folder": ("STRING", {"default": "", "label": "输出文件夹", **zh("输出文件夹", "保存处理结果的文件夹")}),
                "file_types": ("STRING", {"default": "pdf,docx,pptx", "label": "文件类型", **zh("文件类型", "逗号分隔的文件扩展名")}),
            },
            "optional": {
                "converter_options": ("JSON", {"default": "{}", "label": "转换选项", **zh("转换选项", "JSON格式的转换器设置")}),
                "max_threads": ("INT", {"default": 4, "min": 1, "max": 32, "label": "最大线程", **zh("最大线程", "同时处理的最大文件数")}),
            }
        }
    
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("status", "summary")
    FUNCTION = "process"
    CATEGORY = "Docling/批处理"
    OUTPUT_NODE = True

    def process(self, folder_path: str, output_folder: str, file_types: str, 
               converter_options: str = "{}", max_threads: int = 4) -> Tuple[str, str]:
        # 清理路径
        folder_path = clean_path(folder_path)
        output_folder = clean_path(output_folder)
        
        # 验证输入目录
        if not os.path.isdir(folder_path):
            return (f"文件夹不存在: {folder_path}", "")
        
        # 创建输出目录
        os.makedirs(output_folder, exist_ok=True)
        
        # 获取有效扩展名
        valid_exts = [ext.strip().lower() for ext in file_types.split(",")]
        
        # 收集文件
        files_to_process = self.collect_files(folder_path, valid_exts)
        
        if not files_to_process:
            return ("完成", json.dumps({"message": "没有找到可处理的文件"}, ensure_ascii=False))
        
        # 处理文件
        results = self.process_files(files_to_process, output_folder, converter_options, max_threads)
        
        # 生成摘要
        summary = self.generate_summary(results)
        return ("完成", json.dumps(summary, indent=2, ensure_ascii=False))
    
    def collect_files(self, folder_path: str, valid_exts: List[str]) -> List[str]:
        """收集要处理的文件"""
        files = []
        for filename in os.listdir(folder_path):
            file_path = os.path.join(folder_path, filename)
            if not os.path.isfile(file_path):
                continue
                
            ext = Path(filename).suffix.lower().lstrip('.')
            if not ext or ext not in valid_exts:
                continue
                
            files.append(file_path)
        return files
    
    def process_files(self, files: List[str], output_folder: str, converter_options: str, max_threads: int):
        results = []
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max_threads,
            thread_name_prefix="DoclingWorker"
        ) as executor:
            futures = []
            for file_path in files:
                futures.append(executor.submit(
                    self.process_single_file, 
                    file_path, output_folder, converter_options
                ))
            
            for future in concurrent.futures.as_completed(futures):
                results.append(future.result())
        
        return results
    
    def process_single_file(self, file_path: str, output_folder: str, 
                           converter_options: str) -> Dict:
        """处理单个文件"""
        filename = os.path.basename(file_path)
        output_file = os.path.join(output_folder, f"{Path(filename).stem}.json")
        
        try:
            # 使用转换器处理文件
            converter = DoclingConverter()
            json_output, status, _ = converter.convert(
                file_path=file_path,
                format="auto",
                auto_language=True,
                chunking=True,
                enhancements=True,
                output_path=output_file,
                custom_options=converter_options
            )
            
            if "成功" in status:
                return {"file": filename, "status": "成功", "output": output_file}
            else:
                return {"file": filename, "status": "失败", "error": status}
                
        except Exception as e:
            return {"file": filename, "status": "错误", "error": str(e)}
    
    def generate_summary(self, results: List[Dict]) -> Dict:
        """生成处理摘要"""
        success = sum(1 for r in results if r.get("status") == "成功")
        failed = sum(1 for r in results if r.get("status") == "失败")
        errors = sum(1 for r in results if r.get("status") == "错误")
        
        return {
            "处理状态": "完成",
            "文件总数": len(results),
            "成功数量": success,
            "失败数量": failed,
            "错误数量": errors,
            "结果列表": results
        }

# ---------- 插件注册 ----------
NODE_CLASS_MAPPINGS = {
    "DoclingConverter": DoclingConverter,
    "DoclingMetadataExtractor": DoclingMetadataExtractor,
    "DoclingBatchProcessor": DoclingBatchProcessor
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "DoclingConverter": "📄文档转换器",
    "DoclingMetadataExtractor": "🔍元数据提取器",
    "DoclingBatchProcessor": "📂批量处理器"
}

CATEGORY_MAPPINGS = {
    "Docling/文档处理": "文档处理",
    "Docling/批处理": "批处理"
}

def get_custom_categories():
    """获取自定义类别映射"""
    return CATEGORY_MAPPINGS

# 注册自定义类别
comfy.utils.get_custom_categories = get_custom_categories