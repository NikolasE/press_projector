/**
 * Common utilities for the Press Projector System
 * Provides WebSocket client wrapper and SVG manipulation utilities
 */

// WebSocket client wrapper
class WebSocketClient {
    constructor() {
        this.socket = null;
        this.connected = false;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 10;
        this.reconnectDelay = 1000;
    }

    connect() {
        if (this.socket) {
            this.socket.disconnect();
        }

        this.socket = io();
        
        this.socket.on('connect', () => {
            this.connected = true;
            this.reconnectAttempts = 0;
            console.log('WebSocket connected');
        });

        this.socket.on('disconnect', () => {
            this.connected = false;
            console.log('WebSocket disconnected');
            this.attemptReconnect();
        });

        this.socket.on('connect_error', (error) => {
            console.error('WebSocket connection error:', error);
            this.attemptReconnect();
        });

        return this.socket;
    }

    attemptReconnect() {
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
            this.reconnectAttempts++;
            console.log(`Attempting to reconnect (${this.reconnectAttempts}/${this.maxReconnectAttempts})...`);
            
            setTimeout(() => {
                this.connect();
            }, this.reconnectDelay * this.reconnectAttempts);
        } else {
            console.error('Max reconnection attempts reached');
        }
    }

    disconnect() {
        if (this.socket) {
            this.socket.disconnect();
            this.socket = null;
        }
        this.connected = false;
    }

    emit(event, data) {
        if (this.socket && this.connected) {
            this.socket.emit(event, data);
        } else {
            console.warn('WebSocket not connected, cannot emit event:', event);
        }
    }

    on(event, callback) {
        if (this.socket) {
            this.socket.on(event, callback);
        }
    }
}

// SVG manipulation utilities
class SVGUtils {
    static createSVGElement(tag, attributes = {}) {
        const element = document.createElementNS('http://www.w3.org/2000/svg', tag);
        Object.entries(attributes).forEach(([key, value]) => {
            element.setAttribute(key, value);
        });
        return element;
    }

    static createLine(x1, y1, x2, y2, attributes = {}) {
        return this.createSVGElement('line', {
            x1, y1, x2, y2,
            ...attributes
        });
    }

    static createRectangle(x, y, width, height, attributes = {}) {
        return this.createSVGElement('rect', {
            x, y, width, height,
            ...attributes
        });
    }

    static createCircle(cx, cy, r, attributes = {}) {
        return this.createSVGElement('circle', {
            cx, cy, r,
            ...attributes
        });
    }

    static createText(x, y, text, attributes = {}) {
        const element = this.createSVGElement('text', {
            x, y,
            ...attributes
        });
        element.textContent = text;
        return element;
    }

    static createGroup(children = [], attributes = {}) {
        const group = this.createSVGElement('g', attributes);
        children.forEach(child => group.appendChild(child));
        return group;
    }

    static createTransform(translate = {x: 0, y: 0}, rotate = 0, scale = {x: 1, y: 1}) {
        let transform = '';
        
        if (translate.x !== 0 || translate.y !== 0) {
            transform += `translate(${translate.x}, ${translate.y}) `;
        }
        
        if (rotate !== 0) {
            transform += `rotate(${rotate}) `;
        }
        
        if (scale.x !== 1 || scale.y !== 1) {
            transform += `scale(${scale.x}, ${scale.y}) `;
        }
        
        return transform.trim();
    }
}

// Coordinate conversion utilities
class CoordinateConverter {
    constructor(calibrationData) {
        this.calibration = calibrationData;
        this.pixelsPerMm = calibrationData?.pixels_per_mm || 1;
    }

    mmToPixels(mm) {
        return mm * this.pixelsPerMm;
    }

    pixelsToMm(pixels) {
        return pixels / this.pixelsPerMm;
    }

    projectorToPress(x, y) {
        if (!this.calibration?.transformation_matrix) {
            return { x: 0, y: 0 };
        }
        
        // This would use OpenCV perspective transformation
        // For now, return simple conversion
        return {
            x: this.pixelsToMm(x),
            y: this.pixelsToMm(y)
        };
    }

    pressToProjector(x, y) {
        if (!this.calibration?.transformation_matrix) {
            return { x: 0, y: 0 };
        }
        
        // This would use OpenCV perspective transformation
        // For now, return simple conversion
        return {
            x: this.mmToPixels(x),
            y: this.mmToPixels(y)
        };
    }
}

// Drawing element managers
class DrawingElementManager {
    constructor(converter) {
        this.converter = converter;
        this.elements = [];
    }

    addLine(start, end, label = '') {
        const element = {
            type: 'line',
            start: start,
            end: end,
            label: label,
            id: this.generateId()
        };
        this.elements.push(element);
        return element;
    }

    addRectangle(position, width, height, rotation = 0, label = '') {
        const element = {
            type: 'rectangle',
            position: position,
            width: width,
            height: height,
            rotation: rotation,
            label: label,
            id: this.generateId()
        };
        this.elements.push(element);
        return element;
    }

    addCircle(position, radius, label = '') {
        const element = {
            type: 'circle',
            position: position,
            radius: radius,
            label: label,
            id: this.generateId()
        };
        this.elements.push(element);
        return element;
    }

    addImage(position, width, rotation = 0, imageUrl = '', label = '') {
        const element = {
            type: 'image',
            position: position,
            width: width,
            rotation: rotation,
            image_url: imageUrl,
            label: label,
            id: this.generateId()
        };
        this.elements.push(element);
        return element;
    }

    removeElement(id) {
        const index = this.elements.findIndex(el => el.id === id);
        if (index !== -1) {
            this.elements.splice(index, 1);
            return true;
        }
        return false;
    }

    updateElement(id, updates) {
        const element = this.elements.find(el => el.id === id);
        if (element) {
            Object.assign(element, updates);
            return true;
        }
        return false;
    }

    generateId() {
        return 'element_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
    }

    toSVG() {
        const elements = this.elements.map(element => this.elementToSVG(element));
        return elements.join('\n');
    }

    elementToSVG(element) {
        switch (element.type) {
            case 'line':
                return this.lineToSVG(element);
            case 'rectangle':
                return this.rectangleToSVG(element);
            case 'circle':
                return this.circleToSVG(element);
            case 'image':
                return this.imageToSVG(element);
            default:
                return '';
        }
    }

    lineToSVG(element) {
        const start = this.converter.pressToProjector(element.start[0], element.start[1]);
        const end = this.converter.pressToProjector(element.end[0], element.end[1]);
        const lineWidthPx = element.line_width != null ? this.converter.mmToPixels(element.line_width) : 2;
        
        const line = SVGUtils.createLine(start.x, start.y, end.x, end.y, {
            stroke: (element.color || '#00ff00'),
            'stroke-width': lineWidthPx,
            'stroke-dasharray': '5,5'
        });

        let svg = line.outerHTML;
        
        // Don't render labels during rasterization
        // if (element.label) {
        //     const text = SVGUtils.createText(
        //         (start.x + end.x) / 2,
        //         (start.y + end.y) / 2 - 5,
        //         element.label,
        //         {
        //             fill: '#ffffff',
        //             'font-family': 'Arial, sans-serif',
        //             'font-size': '16px',
        //             'text-anchor': 'middle'
        //         }
        //     );
        //     svg += text.outerHTML;
        // }
        
        return svg;
    }

    rectangleToSVG(element) {
        const pos = this.converter.pressToProjector(element.position[0], element.position[1]);
        const width = this.converter.mmToPixels(element.width);
        const height = this.converter.mmToPixels(element.height);
        const lineWidthPx = element.line_width != null ? this.converter.mmToPixels(element.line_width) : 2;
        
        const rect = SVGUtils.createRectangle(pos.x, pos.y, width, height, {
            stroke: (element.color || '#00ffff'),
            'stroke-width': lineWidthPx,
            fill: 'none'
        });

        let svg = rect.outerHTML;
        
        // Don't render labels during rasterization
        // if (element.label) {
        //     const text = SVGUtils.createText(
        //         pos.x + width / 2,
        //         pos.y + height / 2,
        //         element.label,
        //         {
        //             fill: '#ffffff',
        //             'font-family': 'Arial, sans-serif',
        //             'font-size': '16px',
        //             'text-anchor': 'middle'
        //         }
        //     );
        //     svg += text.outerHTML;
        // }
        
        return svg;
    }

    circleToSVG(element) {
        const pos = this.converter.pressToProjector(element.position[0], element.position[1]);
        const radius = this.converter.mmToPixels(element.radius);
        const lineWidthPx = element.line_width != null ? this.converter.mmToPixels(element.line_width) : 2;
        
        const circle = SVGUtils.createCircle(pos.x, pos.y, radius, {
            stroke: (element.color || '#00ffff'),
            'stroke-width': lineWidthPx,
            fill: 'none'
        });

        let svg = circle.outerHTML;
        
        // Don't render labels during rasterization
        // if (element.label) {
        //     const text = SVGUtils.createText(
        //         pos.x,
        //         pos.y + 5,
        //         element.label,
        //         {
        //             fill: '#ffffff',
        //             'font-family': 'Arial, sans-serif',
        //             'font-size': '16px',
        //             'text-anchor': 'middle'
        //         }
        //     );
        //     svg += text.outerHTML;
        // }
        
        return svg;
    }

    imageToSVG(element) {
        const pos = this.converter.pressToProjector(element.position[0], element.position[1]);
        const width = this.converter.mmToPixels(element.width);
        const height = width; // Assume square for now
        
        const image = SVGUtils.createSVGElement('image', {
            x: pos.x,
            y: pos.y,
            width: width,
            height: height,
            href: element.image_url
        });

        return image.outerHTML;
    }
}

// Press boundary pattern generator
class PressBoundaryGenerator {
    constructor(converter) {
        this.converter = converter;
    }

    generatePattern(marginMm = 5.0) {
        if (!this.converter.calibration) {
            return '';
        }

        const calibration = this.converter.calibration;
        const width = calibration.press_width_mm;
        const height = calibration.press_height_mm;

        // Define corners with margin
        const corners = [
            [-marginMm, -marginMm],
            [width + marginMm, -marginMm],
            [width + marginMm, height + marginMm],
            [-marginMm, height + marginMm]
        ];

        // Convert to projector coordinates
        const projectorCorners = corners.map(corner => 
            this.converter.pressToProjector(corner[0], corner[1])
        );

        // Create boundary rectangle
        const points = projectorCorners.map(corner => `${corner.x},${corner.y}`).join(' ');
        const boundary = SVGUtils.createSVGElement('polygon', {
            points: points,
            stroke: '#ffff00',
            'stroke-width': 4,
            fill: 'none'
        });

        // Add corner markers
        const markers = projectorCorners.map((corner, index) => {
            const circle = SVGUtils.createCircle(corner.x, corner.y, 8, {
                fill: '#ffff00'
            });
            const text = SVGUtils.createText(corner.x, corner.y + 5, (index + 1).toString(), {
                fill: 'black',
                'font-size': '12px',
                'text-anchor': 'middle'
            });
            return circle.outerHTML + text.outerHTML;
        }).join('');

        return boundary.outerHTML + markers;
    }
}

// Utility functions
const Utils = {
    // Format numbers for display
    formatNumber(value, decimals = 1) {
        return parseFloat(value).toFixed(decimals);
    },

    // Convert file size to human readable format
    formatFileSize(bytes) {
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        if (bytes === 0) return '0 Bytes';
        const i = Math.floor(Math.log(bytes) / Math.log(1024));
        return Math.round(bytes / Math.pow(1024, i) * 100) / 100 + ' ' + sizes[i];
    },

    // Generate unique ID
    generateId(prefix = 'id') {
        return prefix + '_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
    },

    // Debounce function
    debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    },

    // Throttle function
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
    },

    // Validate email
    isValidEmail(email) {
        const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        return re.test(email);
    },

    // Validate file type
    isValidFileType(filename, allowedTypes) {
        const extension = filename.split('.').pop().toLowerCase();
        return allowedTypes.includes(extension);
    },

    // Get file extension
    getFileExtension(filename) {
        return filename.split('.').pop().toLowerCase();
    },

    // Sanitize filename
    sanitizeFilename(filename) {
        return filename.replace(/[^a-z0-9.-]/gi, '_').toLowerCase();
    }
};

// Export for use in modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        WebSocketClient,
        SVGUtils,
        CoordinateConverter,
        DrawingElementManager,
        PressBoundaryGenerator,
        Utils
    };
}
