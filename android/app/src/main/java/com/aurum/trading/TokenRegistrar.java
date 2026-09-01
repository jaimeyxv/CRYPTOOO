package com.aurum.trading;

import android.webkit.CookieManager;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

final class TokenRegistrar {
    private static final ExecutorService EXECUTOR = Executors.newSingleThreadExecutor();

    private TokenRegistrar() {}

    static void register(String token) {
        if (token == null || token.length() < 20) return;
        EXECUTOR.execute(() -> {
            HttpURLConnection connection = null;
            try {
                URL endpoint = new URL(BuildConfig.AURUM_URL + "/api/dispositivos");
                connection = (HttpURLConnection) endpoint.openConnection();
                connection.setRequestMethod("POST");
                connection.setConnectTimeout(7000);
                connection.setReadTimeout(7000);
                connection.setDoOutput(true);
                connection.setRequestProperty("Content-Type", "application/x-www-form-urlencoded");
                String cookie = CookieManager.getInstance().getCookie(BuildConfig.AURUM_URL);
                if (cookie != null) connection.setRequestProperty("Cookie", cookie);
                String body = "token=" + URLEncoder.encode(token, "UTF-8")
                        + "&label=" + URLEncoder.encode("Aurum Android Beta", "UTF-8");
                try (OutputStream output = connection.getOutputStream()) {
                    output.write(body.getBytes(StandardCharsets.UTF_8));
                }
                connection.getResponseCode();
            } catch (Exception ignored) {
                // Se reintenta al terminar la siguiente carga autenticada del panel.
            } finally {
                if (connection != null) connection.disconnect();
            }
        });
    }
}
