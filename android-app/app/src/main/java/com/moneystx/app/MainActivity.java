package com.moneystx.app;

import android.animation.Animator;
import android.animation.AnimatorListenerAdapter;
import android.annotation.SuppressLint;
import android.app.AlertDialog;
import android.content.Intent;
import android.graphics.Color;
import android.net.ConnectivityManager;
import android.net.NetworkInfo;
import android.net.Uri;
import android.os.Bundle;
import android.view.View;
import android.webkit.*;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.view.WindowCompat;
import androidx.core.view.WindowInsetsControllerCompat;
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;

public class MainActivity extends AppCompatActivity {

    private WebView          webView;
    private ProgressBar      progressBar;
    private View             splash;
    private LinearLayout     offlineView;
    private SwipeRefreshLayout swipeRefresh;

    private static final String APP_URL = "https://moneystx.com";
    private boolean firstLoad = true;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        // Edge-to-edge immersive — matches the app's dark theme
        WindowCompat.setDecorFitsSystemWindows(getWindow(), false);
        getWindow().setStatusBarColor(Color.TRANSPARENT);
        getWindow().setNavigationBarColor(Color.parseColor("#050505"));
        new WindowInsetsControllerCompat(getWindow(), getWindow().getDecorView())
            .setAppearanceLightStatusBars(false);

        setContentView(R.layout.activity_main);

        webView      = findViewById(R.id.webview);
        progressBar  = findViewById(R.id.progress_bar);
        splash       = findViewById(R.id.splash);
        offlineView  = findViewById(R.id.offline_view);
        swipeRefresh = findViewById(R.id.swipe_refresh);

        // SwipeRefresh colours — orange spinner on obsidian
        swipeRefresh.setColorSchemeColors(Color.parseColor("#FF8C00"));
        swipeRefresh.setProgressBackgroundColorSchemeColor(Color.parseColor("#1a1a1a"));
        swipeRefresh.setOnRefreshListener(() -> webView.reload());

        // Retry button on offline screen
        Button retryBtn = findViewById(R.id.retry_btn);
        retryBtn.setOnClickListener(v -> {
            offlineView.setVisibility(View.GONE);
            webView.loadUrl(APP_URL);
        });

        setupWebView();

        if (savedInstanceState != null) {
            webView.restoreState(savedInstanceState);
            hideSplash();
        } else {
            if (isOnline()) {
                webView.loadUrl(APP_URL);
                checkForUpdate();          // silent background update check
            } else {
                hideSplash();
                showOffline();
            }
        }
    }

    // ── In-app update check ───────────────────────────────────────────────────
    // Runs on a background thread; shows a dialog on the main thread only when
    // the server reports a higher version_code than the installed build.
    // NOTE: Web-content changes (frontend, APIs) are always live — no update
    // needed for those. This check only fires when native Android code is bumped.

    private void checkForUpdate() {
        new Thread(() -> {
            try {
                HttpURLConnection conn = (HttpURLConnection)
                    new URL(APP_URL + "/app/version").openConnection();
                conn.setConnectTimeout(6000);
                conn.setReadTimeout(6000);
                conn.setRequestProperty("User-Agent", "MONEYSTX-Android/" + BuildConfig.VERSION_NAME);

                if (conn.getResponseCode() != 200) return;

                StringBuilder sb = new StringBuilder();
                try (BufferedReader r = new BufferedReader(
                        new InputStreamReader(conn.getInputStream()))) {
                    String line;
                    while ((line = r.readLine()) != null) sb.append(line);
                }

                String json = sb.toString();
                // Lightweight parse — no Gson dependency needed
                int latestCode = Integer.parseInt(
                    json.replaceAll(".*\"version_code\"\\s*:\\s*(\\d+).*", "$1"));
                String downloadUrl = json.replaceAll(
                    ".*\"download_url\"\\s*:\\s*\"([^\"]+)\".*", "$1");

                if (latestCode > BuildConfig.VERSION_CODE) {
                    final String dlUrl = downloadUrl;
                    runOnUiThread(() -> showUpdateDialog(dlUrl));
                }
            } catch (Exception ignored) {
                // Network unavailable or server down — silently skip
            }
        }).start();
    }

    private void showUpdateDialog(String downloadUrl) {
        new AlertDialog.Builder(this)
            .setTitle("Update Available")
            .setMessage("A new version of MONEYSTX is available with improvements "
                + "and fixes. Tap Update to download it.")
            .setPositiveButton("Update", (d, w) -> {
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(downloadUrl)));
                } catch (Exception ignored) {}
            })
            .setNegativeButton("Later", null)
            .show();
    }

    @SuppressLint("SetJavaScriptEnabled")
    private void setupWebView() {
        WebSettings s = webView.getSettings();
        s.setJavaScriptEnabled(true);

        // DOM storage (localStorage) — critical for JWT auth token persistence.
        // setDOMStorageEnabled() was removed from the API-34 compile stubs (listed as
        // "always-on"), but on many devices running older WebView it still defaults to
        // false. Use reflection so this compiles against API-34 while still enabling it
        // at runtime everywhere it matters.
        try {
            WebSettings.class
                .getMethod("setDOMStorageEnabled", boolean.class)
                .invoke(s, true);
        } catch (Exception ignored) { /* API-34+ devices: already always-on */ }

        // Cookies — required for session fallback and same-site cookie auth.
        CookieManager cm = CookieManager.getInstance();
        cm.setAcceptCookie(true);
        cm.setAcceptThirdPartyCookies(webView, true);

        s.setCacheMode(WebSettings.LOAD_DEFAULT);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        s.setBuiltInZoomControls(false);
        s.setSupportZoom(false);
        s.setAllowFileAccess(false);
        s.setGeolocationEnabled(false);
        s.setUserAgentString(s.getUserAgentString() + " MONEYSTX-Android/" + BuildConfig.VERSION_NAME);

        // ── Progress bar + splash ─────────────────────────────────────────
        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onProgressChanged(WebView view, int progress) {
                progressBar.setProgress(progress);
                if (progress == 100) {
                    progressBar.setVisibility(View.GONE);
                    swipeRefresh.setRefreshing(false);
                    if (firstLoad) {
                        firstLoad = false;
                        hideSplash();
                    }
                } else {
                    progressBar.setVisibility(View.VISIBLE);
                }
            }
        });

        // ── Link routing + offline handling ──────────────────────────────
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
                String url = req.getUrl().toString();
                if (url.contains("moneystx.com")) return false;
                try { startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url))); }
                catch (Exception ignored) {}
                return true;
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                swipeRefresh.setRefreshing(false);
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest req,
                                        WebResourceError err) {
                if (req.isForMainFrame()) {
                    hideSplash();
                    showOffline();
                }
            }
        });
    }

    // ── Helpers ───────────────────────────────────────────────────────────────

    private void hideSplash() {
        if (splash.getVisibility() != View.VISIBLE) return;
        splash.animate()
            .alpha(0f).setDuration(300)
            .setListener(new AnimatorListenerAdapter() {
                @Override public void onAnimationEnd(Animator a) {
                    splash.setVisibility(View.GONE);
                }
            });
    }

    private void showOffline() {
        offlineView.setVisibility(View.VISIBLE);
        progressBar.setVisibility(View.GONE);
    }

    private boolean isOnline() {
        ConnectivityManager cm =
            (ConnectivityManager) getSystemService(CONNECTIVITY_SERVICE);
        if (cm == null) return false;
        NetworkInfo ni = cm.getActiveNetworkInfo();
        return ni != null && ni.isConnected();
    }

    // ── Lifecycle ─────────────────────────────────────────────────────────────

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        webView.saveState(out);
    }

    @Override
    public void onBackPressed() {
        if (webView.canGoBack()) webView.goBack();
        else super.onBackPressed();
    }

    @Override protected void onPause()  { super.onPause();  webView.onPause();  }
    @Override protected void onResume() { super.onResume(); webView.onResume(); }
}
