if(window.location.pathname==='/login')window.location.replace('/app.html');
if ('serviceWorker' in navigator && window.isSecureContext) navigator.serviceWorker.register('/sw.js').catch(() => {});
