import java.io.FileInputStream;
import java.lang.reflect.Method;
import java.security.cert.CertificateFactory;
import java.security.cert.X509Certificate;

/** Offline check of the JVM's actual blocked-certificate lookup. */
public final class BlockedCertificatesProbe {
    public static void main(String[] args) throws Exception {
        var lookup = Class.forName("sun.security.util.UntrustedCertificates")
                .getMethod("isUntrusted", X509Certificate.class);
        int checked = 0;
        int missing = 0;
        try (var input = new FileInputStream(args[0])) {
            for (var certificate : CertificateFactory.getInstance("X.509").generateCertificates(input)) {
                checked++;
                if (!Boolean.TRUE.equals(lookup.invoke(null, (X509Certificate) certificate))) missing++;
            }
        }
        if (checked != 35 || missing != 0) {
            throw new IllegalStateException("checked=" + checked + ", missing=" + missing);
        }
        System.out.println("Blocked " + checked + " upstream certificates on Java " + System.getProperty("java.version"));
    }
}
