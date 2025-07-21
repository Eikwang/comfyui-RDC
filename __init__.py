import sys
import subprocess
import importlib.util
from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

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