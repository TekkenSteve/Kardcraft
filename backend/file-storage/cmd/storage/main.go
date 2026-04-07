package main

import (
	"context"
	"fmt"
	"log"
	"net"
	nethttp "net/http"
	"os"
	"os/signal"
	"syscall"

	"github.com/sirupsen/logrus"
	"google.golang.org/grpc"
	"google.golang.org/grpc/reflection"

	"file-storage/internal/config"
	httphandler "file-storage/internal/http"
	"file-storage/internal/middleware"
	"file-storage/internal/policy"
	"file-storage/internal/service"
	"file-storage/internal/storage"
	pb "file-storage/pkg/grpc/pb"
)

func main() {
	// Load configuration
	cfg, err := config.LoadConfig("config.yaml")
	if err != nil {
		log.Fatalf("Failed to load config: %v", err)
	}

	// Setup logger
	logger := setupLogger(cfg)
	logger.Info("Starting File Storage Service")

	// Create storage factory
	factory := storage.NewFactory(cfg)

	// Setup middleware chain
	middlewareChain, err := setupMiddleware(cfg, logger)
	if err != nil {
		logger.Fatalf("Failed to setup middleware: %v", err)
	}

	// Create policy engine
	policyEngine := policy.NewPolicyEngine(&cfg.Policies)

	// Create gRPC server
	grpcServer := grpc.NewServer()

	// Register file storage service
	fileStorageService := service.NewFileStorageService(factory, middlewareChain, policyEngine, cfg)
	pb.RegisterFileStorageServiceServer(grpcServer, fileStorageService)

	// Enable reflection for development
	reflection.Register(grpcServer)

	// Create HTTP server
	httpServer := httphandler.NewServer(cfg, factory, middlewareChain, policyEngine, logger)
	httpAddr := cfg.Server.Host + ":8080"
	httpSrv := &nethttp.Server{
		Addr:    httpAddr,
		Handler: httpServer.Handler(),
	}

	// Start gRPC server
	grpcAddr := cfg.GetAddress()
	lis, err := net.Listen("tcp", grpcAddr)
	if err != nil {
		logger.Fatalf("Failed to listen: %v", err)
	}

	logger.Infof("File Storage gRPC server listening on %s", grpcAddr)
	logger.Infof("File Storage HTTP server listening on %s", httpAddr)

	// Handle graceful shutdown
	go func() {
		sigChan := make(chan os.Signal, 1)
		signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)
		<-sigChan

		logger.Info("Shutting down servers...")
		grpcServer.GracefulStop()
		httpSrv.Shutdown(context.Background())
	}()

	// Start HTTP server in goroutine
	go func() {
		if err := httpSrv.ListenAndServe(); err != nil && err != nethttp.ErrServerClosed {
			logger.Fatalf("HTTP server failed: %v", err)
		}
	}()

	// Start gRPC serving (blocking)
	if err := grpcServer.Serve(lis); err != nil {
		logger.Fatalf("Failed to serve: %v", err)
	}
}

// setupLogger configures the logger based on configuration
func setupLogger(cfg *config.Config) *logrus.Logger {
	logger := logrus.New()

	// Set log level
	level, err := logrus.ParseLevel(cfg.Logging.Level)
	if err != nil {
		level = logrus.InfoLevel
	}
	logger.SetLevel(level)

	// Set log format
	if cfg.Logging.Format == "json" {
		logger.SetFormatter(&logrus.JSONFormatter{})
	} else {
		logger.SetFormatter(&logrus.TextFormatter{
			FullTimestamp: true,
		})
	}

	return logger
}

// setupMiddleware configures the middleware chain
func setupMiddleware(cfg *config.Config, logger *logrus.Logger) (*middleware.Chain, error) {
	chain := middleware.NewChain()

	// Add audit middleware if enabled
	if cfg.Middleware.Audit.Enabled {
		auditMiddleware := middleware.NewAuditMiddleware(logger)
		chain.Add(auditMiddleware)
	}

	// Add compression middleware if enabled
	if cfg.Middleware.Compression.Enabled {
		compressionMiddleware := middleware.NewCompressionMiddleware(cfg.Middleware.Compression.Algorithm)
		chain.Add(compressionMiddleware)
	}

	// Add encryption middleware if enabled
	if cfg.Middleware.Encryption.Enabled {
		encryptionMiddleware, err := middleware.NewEncryptionMiddleware(cfg.Middleware.Encryption.Key)
		if err != nil {
			return nil, fmt.Errorf("failed to create encryption middleware: %w", err)
		}
		chain.Add(encryptionMiddleware)
	}

	// Add cache middleware if enabled
	if cfg.Middleware.Cache.Enabled {
		maxSize, err := parseSize(cfg.Middleware.Cache.MaxSize)
		if err != nil {
			return nil, fmt.Errorf("failed to parse cache max size: %w", err)
		}
		cacheMiddleware := middleware.NewCacheMiddleware(cfg.Middleware.Cache.TTL, maxSize)
		chain.Add(cacheMiddleware)
	}

	return chain, nil
}

// parseSize parses a size string like "100MB" into bytes
func parseSize(sizeStr string) (int64, error) {
	if sizeStr == "" {
		return 0, nil
	}
	
	// Simple size parsing - you can make this more sophisticated
	var size int64
	var unit string
	
	n, err := fmt.Sscanf(sizeStr, "%d%s", &size, &unit)
	if err != nil || n != 2 {
		return 0, fmt.Errorf("invalid size format: %s", sizeStr)
	}
	
	switch unit {
	case "B", "b":
		return size, nil
	case "KB", "kb":
		return size * 1024, nil
	case "MB", "mb":
		return size * 1024 * 1024, nil
	case "GB", "gb":
		return size * 1024 * 1024 * 1024, nil
	default:
		return 0, fmt.Errorf("unknown size unit: %s", unit)
	}
}