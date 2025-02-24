FROM ollama/ollama:0.5.12

# Copy the pull script into the image
COPY wait-and-pull.sh /tmp/wait-and-pull.sh

# Ensure it’s executable, then run it at build time
RUN chmod +x /tmp/wait-and-pull.sh \
 && /tmp/wait-and-pull.sh

# Expose Ollama’s default port
EXPOSE 11434

# By default, just serve
ENTRYPOINT ["ollama", "serve"]
