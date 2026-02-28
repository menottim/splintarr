/**
 * Splintarr Dashboard JavaScript
 *
 * Provides client-side interactivity for the dashboard
 */

// Utility function for making API calls
async function apiCall(url, options = {}) {
    const defaultOptions = {
        headers: {
            'Content-Type': 'application/json',
        },
    };

    const mergedOptions = {
        ...defaultOptions,
        ...options,
        headers: {
            ...defaultOptions.headers,
            ...(options.headers || {}),
        },
    };

    try {
        const response = await fetch(url, mergedOptions);
        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || data.message || 'Request failed');
        }

        return { success: true, data };
    } catch (error) {
        return { success: false, error: error.message };
    }
}

// Show toast notification
function showNotification(message, type = 'error') {
    const existing = document.getElementById('toast-notification');
    if (existing) existing.remove();

    const toast = document.createElement('div');
    toast.id = 'toast-notification';
    toast.setAttribute('role', 'alert');
    toast.style.cssText = 'position:fixed;top:1rem;right:1rem;z-index:9999;padding:0.75rem 1rem;border-radius:0.25rem;font-size:0.875rem;max-width:400px;box-shadow:0 4px 12px rgba(0,0,0,0.4);transition:opacity 0.3s;';

    if (type === 'error') {
        toast.style.background = 'rgba(255,85,85,0.15)';
        toast.style.border = '1px solid #ff5555';
        toast.style.color = '#ff5555';
    } else if (type === 'success') {
        toast.style.background = 'rgba(72,199,116,0.15)';
        toast.style.border = '1px solid #48c774';
        toast.style.color = '#48c774';
    } else {
        toast.style.background = 'rgba(212,160,23,0.15)';
        toast.style.border = '1px solid #D4A017';
        toast.style.color = '#D4A017';
    }

    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => { toast.style.opacity = '0'; setTimeout(() => toast.remove(), 300); }, 5000);
}

// Confirm dialog
function confirmAction(message) {
    return window.confirm(message);
}

// Format datetime
function formatDateTime(dateString) {
    if (!dateString) return 'Never';

    const date = new Date(dateString);
    return date.toLocaleString();
}

// Format time ago
function formatTimeAgo(dateString) {
    if (!dateString) return 'Never';

    const date = new Date(dateString);
    const now = new Date();
    const diff = now - date;
    const seconds = Math.floor(diff / 1000);

    if (seconds < 60) return 'just now';
    if (seconds < 3600) return Math.floor(seconds / 60) + ' minutes ago';
    if (seconds < 86400) return Math.floor(seconds / 3600) + ' hours ago';
    if (seconds < 604800) return Math.floor(seconds / 86400) + ' days ago';

    return date.toLocaleDateString();
}

// Auto-refresh functionality
class AutoRefresh {
    constructor(callback, interval = 30000) {
        this.callback = callback;
        this.interval = interval;
        this.timerId = null;
    }

    start() {
        if (this.timerId) return;
        this.timerId = setInterval(this.callback, this.interval);
    }

    stop() {
        if (this.timerId) {
            clearInterval(this.timerId);
            this.timerId = null;
        }
    }

    restart() {
        this.stop();
        this.start();
    }
}

// Initialize auto-refresh for dashboard stats
if (window.location.pathname === '/dashboard') {
    const statsRefresh = new AutoRefresh(async () => {
        const result = await apiCall('/api/dashboard/stats');
        if (result.success) {
            // Update UI with new stats (would require more complex DOM manipulation)
        }
    }, 30000);

    // Start auto-refresh when page loads
    document.addEventListener('DOMContentLoaded', () => {
        statsRefresh.start();
    });

    // Stop auto-refresh when page is hidden (battery optimization)
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) {
            statsRefresh.stop();
        } else {
            statsRefresh.start();
        }
    });
}

// Form validation helpers
function validatePassword(password) {
    const errors = [];

    if (password.length < 12) {
        errors.push('Password must be at least 12 characters long');
    }

    if (!/[a-z]/.test(password)) {
        errors.push('Password must contain at least one lowercase letter');
    }

    if (!/[A-Z]/.test(password)) {
        errors.push('Password must contain at least one uppercase letter');
    }

    if (!/\d/.test(password)) {
        errors.push('Password must contain at least one digit');
    }

    if (!/[!@#$%^&*(),.?":{}|<>_\-+=\[\]\\/'`~;]/.test(password)) {
        errors.push('Password must contain at least one special character');
    }

    return errors;
}

function validateUsername(username) {
    const errors = [];

    if (username.length < 3 || username.length > 32) {
        errors.push('Username must be 3-32 characters long');
    }

    if (!/^[a-zA-Z][a-zA-Z0-9_]*$/.test(username)) {
        errors.push('Username must start with a letter and contain only alphanumeric characters and underscore');
    }

    return errors;
}

// Sanitize a string for safe insertion into innerHTML
function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = String(str);
    return div.innerHTML;
}

// Export functions for use in templates
window.Splintarr = {
    apiCall,
    showNotification,
    formatDateTime,
    formatTimeAgo,
    validatePassword,
    validateUsername,
    escapeHtml,
    AutoRefresh,
};

// Dashboard initialized
