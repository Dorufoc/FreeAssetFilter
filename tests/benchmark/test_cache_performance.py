"""
缓存性能基准测试
"""
import time

class TestCachePerformance:
    
    def test_lru_k_cache_operations(self):
        """LRU-K缓存操作性能测试"""
        from freeassetfilter.core.lru_k_cache import LRUKCache
        from PySide6.QtGui import QPixmap
        
        cache = LRUKCache(max_memory=100*1024*1024, k=2)
        
        pixmap = QPixmap(128, 128)
        
        start = time.time()
        for i in range(1000):
            cache.put(f"key_{i}", pixmap, 128*128*4)
        put_time = time.time() - start
        
        start = time.time()
        for i in range(1000):
            cache.get(f"key_{i}")
        get_time = time.time() - start
        
        print(f"\nPut 1000次: {put_time*1000:.2f}ms")
        print(f"Get 1000次: {get_time*1000:.2f}ms")
        print(f"平均Put: {put_time:.3f}ms")
        print(f"平均Get: {get_time:.3f}ms")
        
        assert get_time / 1000 < 0.001, "Get操作延迟过高"
