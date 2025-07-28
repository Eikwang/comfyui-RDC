import sys
import subprocess
import importlib.util
import comfy.utils 

CATEGORY_MAPPINGS = {}

# 导入所有节点映射
from .node.AnythingLLMProcessor import NODE_CLASS_MAPPINGS as llm_mappings
from .node.AnythingLLMProcessor import NODE_DISPLAY_NAME_MAPPINGS as llm_display_mappings
from .node.DoclingConverterQA import NODE_CLASS_MAPPINGS as qa_mappings
from .node.DoclingConverterQA import NODE_DISPLAY_NAME_MAPPINGS as qa_display_mappings
from .node.nodes import NODE_CLASS_MAPPINGS as nodes_mappings
from .node.nodes import NODE_DISPLAY_NAME_MAPPINGS as nodes_display_mappings

# 合并节点映射
NODE_CLASS_MAPPINGS = {**llm_mappings, **qa_mappings, **nodes_mappings}
NODE_DISPLAY_NAME_MAPPINGS = {**llm_display_mappings, **qa_display_mappings, **nodes_display_mappings}

# 合并类别映射
CATEGORY_MAPPINGS = {}
CATEGORY_MAPPINGS.update(getattr(llm_mappings, 'CATEGORY_MAPPINGS', {}))
# 移除错误的 md_mappings 引用
CATEGORY_MAPPINGS.update(getattr(qa_mappings, 'CATEGORY_MAPPINGS', {}))
CATEGORY_MAPPINGS.update(getattr(nodes_mappings, 'CATEGORY_MAPPINGS', {}))

# 注册自定义类别
comfy.utils.get_custom_categories = lambda: CATEGORY_MAPPINGS

WEB_DIRECTORY = "./web"

# 检查并安装依赖
def install_dependencies():
    dependencies = [
        "docling",
        "easyocr",
        "rapidocr_onnxruntime",
        "transformers",
        "tiktoken"
    ]
    
    missing_deps = []
    for dep in dependencies:
        dep_name = dep.split('>=')[0] if '>=' in dep else dep
        if importlib.util.find_spec(dep_name) is None:
            missing_deps.append(dep)
    
    if missing_deps:
        print(f"安装Docling插件依赖: {', '.join(missing_deps)}")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", *missing_deps])
            print("依赖安装成功!")
        except subprocess.CalledProcessError:
            print("依赖安装失败，请手动运行: "
                  f"pip install {' '.join(missing_deps)}")

# 初始化插件
install_dependencies()

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS', 'WEB_DIRECTORY']