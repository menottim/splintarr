/**
 * Vibe-Quality-Searcharr Dashboard JavaScript
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

// Show notification (using browser alert for simplicity)
function showNotification(message, type = 'info') {
    // In a production app, this would use a toast/notification library
    if (type === 'error') {
        alert('Error: ' + message);
    }
    // Success/info notifications are silent in production to avoid
    // leaking application internals via browser console
}

// Confirm dialog
function confirm(message) {
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

// Export functions for use in templates
window.QualitySearcharr = {
    apiCall,
    showNotification,
    formatDateTime,
    formatTimeAgo,
    validatePassword,
    validateUsername,
    AutoRefresh,
};

// Dashboard initialized
