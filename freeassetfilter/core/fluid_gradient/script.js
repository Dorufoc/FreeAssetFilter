class FluidGradient {
    constructor() {
        this.config = {
            scrollThreshold: 0.1,
            colorTransitionDuration: 1500,
            performanceMode: false
        };
        
        this.elements = {
            layers: null,
            scrollIndicator: null,
            themeButtons: null
        };
        
        this.state = {
            currentTheme: 'sunset',
            scrollProgress: 0,
            lastScrollY: 0,
            isScrolling: false,
            scrollTimeout: null
        };
        
        this.colorThemes = {
            sunset: {
                colors: ['#ff6b6b', '#feca57', '#ff9ff3', '#f368e0', '#ff4757'],
                layerColors: ['#ff6b6b', '#feca57', '#ff9ff3', '#f368e0', '#ff4757', '#ff6b6b', '#ff9ff3', '#feca57', '#f368e0', '#ff4757']
            },
            ocean: {
                colors: ['#0abde3', '#10ac84', '#00d2d3', '#54a0ff', '#2e86de'],
                layerColors: ['#0abde3', '#10ac84', '#00d2d3', '#54a0ff', '#2e86de', '#0abde3', '#00d2d3', '#10ac84', '#54a0ff', '#2e86de']
            },
            aurora: {
                colors: ['#00ff87', '#60efff', '#0061ff', '#ff00ff', '#00ffcc'],
                layerColors: ['#00ff87', '#60efff', '#0061ff', '#ff00ff', '#00ffcc', '#00ff87', '#0061ff', '#60efff', '#ff00ff', '#00ffcc']
            }
        };
        
        this.init();
    }
    
    init() {
        this.cacheElements();
        this.bindEvents();
        this.updateScrollProgress();
        this.checkPerformance();
    }
    
    cacheElements() {
        this.elements.layers = document.querySelectorAll('.gradient-layer');
        this.elements.scrollIndicator = document.getElementById('scrollIndicator');
        this.elements.themeButtons = document.querySelectorAll('.theme-btn');
    }
    
    bindEvents() {
        window.addEventListener('scroll', this.throttle(() => {
            this.handleScroll();
        }, 16));
        
        window.addEventListener('resize', this.debounce(() => {
            this.handleResize();
        }, 250));
        
        document.addEventListener('DOMContentLoaded', () => {
            this.updateScrollProgress();
        });
    }
    
    handleScroll() {
        this.updateScrollProgress();
        this.updateLayersByScroll();
        this.toggleScrollIndicator();
        
        this.state.isScrolling = true;
        
        clearTimeout(this.state.scrollTimeout);
        this.state.scrollTimeout = setTimeout(() => {
            this.state.isScrolling = false;
        }, 150);
    }
    
    handleResize() {
        this.updateScrollProgress();
    }
    
    updateScrollProgress() {
        const scrollY = window.scrollY;
        const windowHeight = window.innerHeight;
        const documentHeight = document.documentElement.scrollHeight - windowHeight;
        
        this.state.scrollProgress = documentHeight > 0 ? scrollY / documentHeight : 0;
    }
    
    updateLayersByScroll() {
        const progress = this.state.scrollProgress;
        const layers = this.elements.layers;
        
        if (!layers.length) return;
        
        layers.forEach((layer, index) => {
            const baseOpacity = this.getLayerBaseOpacity(index);
            const scrollOffset = this.getLayerScrollOffset(index, progress);
            const scaleEffect = this.getLayerScaleEffect(index, progress);
            
            layer.style.opacity = Math.max(0, Math.min(1, baseOpacity + scrollOffset));
            layer.style.transform = `${this.getLayerBaseTransform(index)} scale(${scaleEffect})`;
        });
    }
    
    getLayerBaseOpacity(index) {
        const opacities = [0.6, 0.5, 0.55, 0.45, 0.5, 0.35, 0.4, 0.3, 0.35, 0.25];
        return opacities[index] || 0.5;
    }
    
    getLayerScrollOffset(index, progress) {
        const offsets = [
            (progress - 0.5) * 0.3,
            (progress - 0.3) * 0.25,
            (progress - 0.7) * 0.28,
            (progress - 0.4) * 0.22,
            (progress - 0.6) * 0.26,
            (progress - 0.2) * 0.2,
            (progress - 0.8) * 0.24,
            (progress - 0.1) * 0.18,
            (progress - 0.9) * 0.22,
            (progress - 0.05) * 0.16
        ];
        return offsets[index] || 0;
    }
    
    getLayerScaleEffect(index, progress) {
        const baseScales = [1, 1, 1, 1, 1, 1, 1, 1, 1, 1];
        const scaleMultipliers = [0.15, 0.12, 0.18, 0.1, 0.15, 0.2, 0.15, 0.25, 0.05, 0.3];
        const baseScale = baseScales[index] || 1;
        const multiplier = scaleMultipliers[index] || 0.1;
        
        return baseScale + (progress * multiplier);
    }
    
    getLayerBaseTransform(index) {
        const transforms = [
            'translate(0, 0)',
            'translate(0, 0)',
            'translate(0, 0)',
            'translate(0, 0)',
            'translate(0, 0)',
            'translate(0, 0)',
            'translate(0, 0)',
            'translate(0, 0)',
            'translate(0, 0)',
            'translate(0, 0)'
        ];
        return transforms[index] || 'translate(0, 0)';
    }
    
    toggleScrollIndicator() {
        const indicator = this.elements.scrollIndicator;
        if (!indicator) return;
        
        if (this.state.scrollProgress > this.config.scrollThreshold) {
            indicator.classList.add('hidden');
        } else {
            indicator.classList.remove('hidden');
        }
    }
    
    applyTheme(themeName, animate = true) {
        const theme = this.colorThemes[themeName];
        if (!theme) return;
        
        this.state.currentTheme = themeName;
        
        const root = document.documentElement;
        
        if (animate) {
            root.style.setProperty('--transition-duration', `${this.config.colorTransitionDuration}ms`);
        }
        
        theme.colors.forEach((color, i) => {
            root.style.setProperty(`--color-${i + 1}`, color);
        });
        
        this.updateLayerColors(theme.layerColors, animate);
        this.updateThemeButtons(themeName);
    }
    
    updateLayerColors(layerColors, animate) {
        const layers = this.elements.layers;
        if (!layers.length) return;
        
        layers.forEach((layer, index) => {
            const color = layerColors[index];
            if (!color) return;
            
            if (animate) {
                layer.style.transition = `background-color ${this.config.colorTransitionDuration}ms ease, opacity 0.5s ease, transform 0.5s ease`;
            }
            
            const gradient = this.getLayerGradient(index, color);
            layer.style.background = gradient;
        });
    }
    
    getLayerGradient(index, color) {
        const gradients = [
            `radial-gradient(ellipse 120% 120% at 50% 50%, ${color} 0%, transparent 50%)`,
            `radial-gradient(ellipse 100% 100% at 20% 30%, ${color} 0%, transparent 45%)`,
            `radial-gradient(ellipse 110% 110% at 80% 20%, ${color} 0%, transparent 45%)`,
            `radial-gradient(ellipse 90% 90% at 40% 70%, ${color} 0%, transparent 45%)`,
            `radial-gradient(ellipse 100% 100% at 70% 80%, ${color} 0%, transparent 45%)`,
            `radial-gradient(ellipse 130% 130% at 30% 60%, ${color} 0%, transparent 50%)`,
            `radial-gradient(ellipse 80% 80% at 60% 40%, ${color} 0%, transparent 45%)`,
            `radial-gradient(ellipse 140% 140% at 10% 80%, ${color} 0%, transparent 50%)`,
            `radial-gradient(ellipse 70% 70% at 90% 50%, ${color} 0%, transparent 45%)`,
            `radial-gradient(ellipse 150% 150% at 50% 10%, ${color} 0%, transparent 50%)`
        ];
        
        return gradients[index] || `radial-gradient(circle, ${color} 0%, transparent 50%)`;
    }
    
    updateThemeButtons(activeTheme) {
        const buttons = this.elements.themeButtons;
        if (!buttons.length) return;
        
        buttons.forEach(button => {
            const theme = button.getAttribute('data-theme');
            if (theme === activeTheme) {
                button.classList.add('active');
            } else {
                button.classList.remove('active');
            }
        });
    }
    
    checkPerformance() {
        if (this.config.performanceMode) {
            document.body.classList.add('performance-mode');
        }
    }
    
    throttle(func, limit) {
        let inThrottle;
        return function() {
            const args = arguments;
            const context = this;
            if (!inThrottle) {
                func.apply(context, args);
                inThrottle = true;
                setTimeout(() => inThrottle = false, limit);
            }
        };
    }
    
    debounce(func, wait) {
        let timeout;
        return function() {
            const context = this;
            const args = arguments;
            clearTimeout(timeout);
            timeout = setTimeout(() => func.apply(context, args), wait);
        };
    }
}

const fluidGradient = new FluidGradient();

function switchTheme(theme) {
    fluidGradient.applyTheme(theme);
}

window.addEventListener('load', () => {
    fluidGradient.updateScrollProgress();
});
