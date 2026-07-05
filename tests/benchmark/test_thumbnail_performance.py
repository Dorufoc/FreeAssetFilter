"""
缩略图生成性能基准测试
"""
import time
import os
import tempfile
from PIL import Image
import numpy as np

def create_test_image(path: str, size: tuple = (1920, 1080)):
    """创建测试图像"""
    img = Image.new('RGB', size, color=(255, 0, 0))
    img.save(path, 'JPEG', quality=95)

class TestThumbnailPerformance:
    """缩略图性能测试类"""
    
    def setup_method(self):
        """测试前准备"""
        self.temp_dir = tempfile.mkdtemp()
        self.test_images = []
        
        for i in range(100):
            path = os.path.join(self.temp_dir, f"test_{i}.jpg")
            create_test_image(path)
            self.test_images.append(path)
    
    def teardown_method(self):
        """测试后清理"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_single_thumbnail_generation(self):
        """单张缩略图生成性能测试"""
        from freeassetfilter.core.thumbnail_manager import ThumbnailManager
        
        manager = ThumbnailManager()
        
        manager.create_thumbnail(self.test_images[0])
        
        start = time.time()
        for _ in range(10):
            manager.create_thumbnail(self.test_images[0], force_regenerate=True)
        elapsed = time.time() - start
        
        avg_time = elapsed / 10
        print(f"\n单张缩略图平均生成时间: {avg_time*1000:.2f}ms")
        
        assert avg_time < 0.2, f"生成时间过长: {avg_time*1000:.2f}ms"
    
    def test_batch_thumbnail_generation(self):
        """批量缩略图生成性能测试"""
        from freeassetfilter.core.thumbnail_manager import ThumbnailManager
        
        manager = ThumbnailManager()
        
        start = time.time()
        for path in self.test_images[:50]:
            manager.create_thumbnail(path)
        elapsed = time.time() - start
        
        print(f"\n50张缩略图生成时间: {elapsed:.2f}s")
        print(f"平均每张: {elapsed/50*1000:.2f}ms")
    
    def test_cache_hit_rate(self):
        """缓存命中率测试"""
        from freeassetfilter.core.thumbnail_manager import ThumbnailManager
        
        manager = ThumbnailManager()
        
        for path in self.test_images[:20]:
            manager.create_thumbnail(path)
        
        start = time.time()
        for path in self.test_images[:20]:
            manager.create_thumbnail(path)
        elapsed = time.time() - start
        
        stats = manager.get_cache_stats()
        print(f"\n缓存命中率: {stats['hit_rate']:.2%}")
        print(f"缓存请求时间: {elapsed*1000:.2f}ms")
        
        assert stats['hit_rate'] > 0.85, f"缓存命中率过低: {stats['hit_rate']:.2%}"

if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "-s"])
