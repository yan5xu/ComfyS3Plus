import os
import json
import tempfile
import numpy as np
import time
from PIL import Image
from PIL.PngImagePlugin import PngInfo
from colorthief import ColorThief
from comfy.cli_args import args

from ..client_s3 import get_s3_instance_plus


class SaveImageWebpS3:
    def __init__(self):
        base_dir = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
        )
        self.temp_dir = os.path.join(base_dir, "temp/")
        self.type = "output"
        self.prefix_append = ""
        self.compress_level = 4

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                # 功能参数相关
                "images": ("IMAGE", {}),
                "filename_prefix": ("STRING", {"default": "Image"}),
                # s3 存储相关
                "version": ("STRING", {"multiline": False, "default": ""}),
                "region": ("STRING", {"multiline": False, "default": ""}),
                "access_key": ("STRING", {"multiline": False, "default": ""}),
                "secret_key": ("STRING", {"multiline": False, "default": ""}),
                "bucket_name": ("STRING", {"multiline": False, "default": ""}),
                "endpoint_url": ("STRING", {"multiline": False, "default": ""}),
                "output_dir": ("STRING", {"multiline": False, "default": ""}),
                "quality": ("FLOAT", {"multiline": False, "default": 0}),
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("s3_image_paths",)
    FUNCTION = "save_images"
    OUTPUT_NODE = True
    OUTPUT_IS_LIST = (True,)
    CATEGORY = "ComfyS3Plus"

    def save_images(
        # base param
        self,
        images,
        filename_prefix,
        # s3 存储相关
        version,
        region,
        access_key,
        secret_key,
        bucket_name,
        endpoint_url,
        output_dir,
        # quality 需要单独补充
        quality,
        # hidden param
        prompt=None,
        extra_pnginfo=None,
    ):
        S3_INSTANCE = get_s3_instance_plus(
            version=version,
            region=region,
            access_key=access_key,
            secret_key=secret_key,
            bucket_name=bucket_name,
            endpoint_url=endpoint_url,
            output_dir=output_dir,
        )
        filename_prefix += f"{ self.prefix_append }{ int(round(time.time() * 1000)) }"
        full_output_folder, filename, counter, subfolder, filename_prefix = (
            S3_INSTANCE.get_save_path(
                filename_prefix, images[0].shape[1], images[0].shape[0]
            )
        )
        results = list()
        s3_image_paths = list()

        for image in images:
            i = 255.0 * image.cpu().numpy()
            img = Image.fromarray(np.clip(i, 0, 255).astype(np.uint8))

            # 设定最终存入图片的 metadata 为 None，避免 workflow 中的敏感信息泄漏
            metadata = None
            file = f"{filename}_{counter:05}_.png"
            temp_file = None
            try:
                # Create a temporary file
                with tempfile.NamedTemporaryFile(
                    delete=False, suffix=".png"
                ) as temp_file:
                    temp_file_path = temp_file.name

                    # Save the image to the temporary file as PNG
                    img.save(
                        temp_file_path,
                        format="PNG",
                        pnginfo=metadata,
                        compress_level=self.compress_level,
                    )

                    # 获取图片信息
                    width, height = img.size
                    file_size = os.path.getsize(temp_file_path)
                    color_thief = ColorThief(temp_file_path)
                    color = color_thief.get_color(quality=1)
                    hex_color = "#{:02X}{:02X}{:02X}".format(color[0], color[1], color[2])
                    print(f"color: {hex_color}")
                    # 设置 S3 元数据
                    extra_args = {
                        "ContentType": "image/png",
                        "Metadata": {
                            "width": str(width),
                            "height": str(height),
                            "size": str(file_size),
                            "type": "png",
                            "color": hex_color,
                        },
                    }
                    print(f"extra_args: {extra_args}")

                    # Upload the temporary file to S3 with metadata
                    s3_path = os.path.join(full_output_folder, file)
                    file_path = S3_INSTANCE.upload_file(
                        temp_file_path, s3_path, extra_args=extra_args
                    )

                    # 创建包含图片信息的结果
                    image_info = {
                        "key": file_path,
                        "width": width,
                        "height": height,
                        "size": file_size,
                        "type": "png",
                    }

                    # Add the s3 path to the s3_image_paths list
                    s3_image_paths.append(image_info)

                    # Add the result to the results list
                    results.append(
                        {
                            "filename": file,
                            "subfolder": subfolder,
                            "type": self.type,
                            "key": file_path,
                            "width": width,
                            "height": height,
                            "size": file_size,
                            "type": "png",
                        }
                    )
                    counter += 1

            finally:
                # Delete the temporary file
                if temp_file_path and os.path.exists(temp_file_path):
                    os.remove(temp_file_path)

        return {"ui": {"images": results}, "result": (s3_image_paths,)}
