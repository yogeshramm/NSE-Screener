package com.moneystx.app;

import android.animation.Animator;
import android.animation.AnimatorListenerAdapter;
import android.annotation.SuppressLint;
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
            } else {
                hideSplash();
                showOffline();
            }
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    private void setupWebView() {
        WebSettings s = webView.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDOMStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setCacheMode(WebSettings.LOAD_DEFAULT);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        s.setBuiltInZoomControls(false);
        s.setSupportZoom(false);
        s.setAllowFileAccess(false);
        s.setGeolocationEnabled(false);
        s.setUserAgentString(s.getUserAgentString() + " MONEYSTX-Android/2.0");

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
