// פונקציית עזר לזיהוי שם וגרסת הדפדפן
function getBrowserInfo() {
    var ua = navigator.userAgent, tem, 
    M = ua.match(/(opera|chrome|safari|firefox|msie|trident(?=\/))\/?\s*(\d+)/i) || [];
    if(/trident/i.test(M[1])){
        tem =  /\brv[ :]+(\d+)/g.exec(ua) || [];
        return {name:'IE',version:(tem[1] || '')};
    }
    if(M[1] === 'Chrome'){
        tem = ua.match(/\b(OPR|Edge?)\/(\d+)/);
        if(tem != null) return {name:tem[1].replace('OPR', 'Opera'), version:tem[2]};
    }
    M = M[2] ? [M[1], M[2]] : [navigator.appName, navigator.appVersion, '-?'];
    if((tem = ua.match(/version\/(\d+)/i))!= null) M.splice(1, 1, tem[1]);
    return {
        name: M[0],
        version: M[1]
    };
}

// פונקציית עזר לזיהוי מערכת ההפעלה
function getOS() {
    var userAgent = window.navigator.userAgent,
        platform = window.navigator.platform,
        macosPlatforms = ['Macintosh', 'MacIntel', 'MacPPC', 'Mac68K'],
        windowsPlatforms = ['Win32', 'Win64', 'Windows', 'WinCE'],
        iosPlatforms = ['iPhone', 'iPad', 'iPod'],
        os = 'Unknown';

    if (macosPlatforms.indexOf(platform) !== -1) { os = 'Mac OS'; }
    else if (iosPlatforms.indexOf(platform) !== -1) { os = 'iOS'; }
    else if (windowsPlatforms.indexOf(platform) !== -1) { os = 'Windows'; }
    else if (/Android/.test(userAgent)) { os = 'Android'; }
    else if (!os && /Linux/.test(platform)) { os = 'Linux'; }
    return os;
}

// הפונקציה המרכזית לאיסוף ושליחת הנתונים
async function collectAndSubmitData() {
    let ipAddress = 'Unknown';

    // 1. שליפת כתובת ה-IP
    try {
        const ipResponse = await fetch('https://api.ipify.org?format=json');
        const ipData = await ipResponse.json();
        ipAddress = ipData.ip;
    } catch (error) {
        console.error("שגיאה בשליפת כתובת IP:", error);
    }

    // 2. איסוף שאר הנתונים
    const browser = getBrowserInfo();
    const os = getOS();
    const isMobile = /Mobile|Android|iP(ad|hone|od)|IEMobile|BlackBerry|Kindle|Silk-Accelerated|(hpw|web)OS|Opera M(obi|ini)/.test(navigator.userAgent);
    
    // מזהי השדות שחולצו מקובץ ה-HTML
    const formData = {
        'entry.1507352604': window.location.href, // כתובת URL של גלישה
        'entry.725280422': ipAddress,             // כתובת IP
        'entry.1000880992': browser.name,         // שם דפדפן
        'entry.851613182': browser.version,       // גרסת דפדפן
        'entry.606656416': os,                    // מערכת הפעלה
        'entry.389497305': isMobile ? 'Mobile' : 'Desktop', // סוג מכשיר
        'entry.940014690': navigator.language,    // שפת המערכת
        'entry.1194450794': navigator.platform,   // פלטפורמה
        'entry.477744560': window.screen.width + 'x' + window.screen.height, // רזולוציית מסך
        'entry.1922220265': window.screen.availWidth + 'x' + window.screen.availHeight, // שטח עבודה זמין
        'entry.804050135': navigator.connection ? navigator.connection.effectiveType : 'Unknown', // סוג חיבור
        'entry.1743195767': document.referrer     // Referrer
    };

    // 3. יצירת פרמטרים לשליחה ב-POST
    const formUrl = 'https://docs.google.com/forms/u/0/d/e/1FAIpQLSfYuWNbvH8yIQFit8hVzDw0FS4B5r_ftobehbFKUbUafsu4mQ/formResponse';
    const params = new URLSearchParams(formData);

    // 4. שליחת הנתונים ל-Google Forms
    try {
        await fetch(formUrl, {
            method: 'POST',
            mode: 'no-cors', // חובה כדי לעקוף שגיאות CORS של גוגל
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            body: params.toString()
        });
        console.log("הנתונים נשלחו בהצלחה לטופס.");
    } catch (error) {
        console.error("שגיאה בשליחת הנתונים:", error);
    }
}

// הפעלת הפונקציה
collectAndSubmitData();
