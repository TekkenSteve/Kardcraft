package main

import (
	"context"
	"fmt"
	"io"
	"log"
	"strings"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"

	pb "file-storage/pkg/grpc/pb"
)

func main() {
	// Connect to the server
	conn, err := grpc.Dial("localhost:50054", grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		log.Fatalf("Failed to connect: %v", err)
	}
	defer conn.Close()

	client := pb.NewFileStorageServiceClient(conn)

	// Test health check
	fmt.Println("=== Health Check ===")
	healthResp, err := client.GetHealth(context.Background(), &pb.HealthRequest{})
	if err != nil {
		log.Fatalf("Health check failed: %v", err)
	}
	fmt.Printf("Status: %s\n", healthResp.Status)
	fmt.Printf("Details: %v\n", healthResp.Details)

	// Test upload
	fmt.Println("\n=== Upload Test ===")
	testData := "Hello, World! This is a test file."
	key := "test/hello.txt"
	
	if err := uploadFile(client, key, strings.NewReader(testData), "text/plain"); err != nil {
		log.Fatalf("Upload failed: %v", err)
	}
	fmt.Printf("Successfully uploaded file: %s\n", key)

	// Test exists
	fmt.Println("\n=== Exists Test ===")
	existsResp, err := client.Exists(context.Background(), &pb.ExistsRequest{Key: key})
	if err != nil {
		log.Fatalf("Exists check failed: %v", err)
	}
	fmt.Printf("File exists: %t\n", existsResp.Exists)

	// Test download
	fmt.Println("\n=== Download Test ===")
	downloadedData, err := downloadFile(client, key)
	if err != nil {
		log.Fatalf("Download failed: %v", err)
	}
	fmt.Printf("Downloaded data: %s\n", string(downloadedData))

	// Test list
	fmt.Println("\n=== List Test ===")
	listResp, err := client.List(context.Background(), &pb.ListRequest{
		Prefix: "test/",
		Limit:  10,
	})
	if err != nil {
		log.Fatalf("List failed: %v", err)
	}
	fmt.Printf("Found %d files:\n", len(listResp.Files))
	for _, file := range listResp.Files {
		fmt.Printf("  - %s (%d bytes)\n", file.Key, file.Size)
	}

	// Test metadata
	fmt.Println("\n=== Metadata Test ===")
	metadataResp, err := client.GetMetadata(context.Background(), &pb.GetMetadataRequest{Key: key})
	if err != nil {
		log.Fatalf("Get metadata failed: %v", err)
	}
	fmt.Printf("Content Type: %s\n", metadataResp.Metadata.ContentType)
	fmt.Printf("Content Length: %d\n", metadataResp.Metadata.ContentLength)

	// Test presigned URL (if supported)
	fmt.Println("\n=== Presigned URL Test ===")
	urlResp, err := client.GeneratePresignedURL(context.Background(), &pb.GeneratePresignedURLRequest{
		Key:           key,
		ExpirySeconds: 3600, // 1 hour
		Operation:     pb.Operation_READ,
	})
	if err != nil {
		fmt.Printf("Presigned URL generation failed (may not be supported): %v\n", err)
	} else {
		fmt.Printf("Presigned URL: %s\n", urlResp.Url)
		fmt.Printf("Expires at: %s\n", urlResp.ExpiresAt.AsTime().Format(time.RFC3339))
	}

	// Test delete
	fmt.Println("\n=== Delete Test ===")
	deleteResp, err := client.Delete(context.Background(), &pb.DeleteRequest{Key: key})
	if err != nil {
		log.Fatalf("Delete failed: %v", err)
	}
	fmt.Printf("Delete successful: %t\n", deleteResp.Success)

	// Verify deletion
	existsResp, err = client.Exists(context.Background(), &pb.ExistsRequest{Key: key})
	if err != nil {
		log.Fatalf("Exists check after delete failed: %v", err)
	}
	fmt.Printf("File exists after delete: %t\n", existsResp.Exists)

	fmt.Println("\n=== All tests completed successfully! ===")
}

// uploadFile uploads a file using streaming
func uploadFile(client pb.FileStorageServiceClient, key string, reader io.Reader, contentType string) error {
	stream, err := client.Upload(context.Background())
	if err != nil {
		return err
	}

	// Send metadata first
	metadata := &pb.UploadRequest{
		Data: &pb.UploadRequest_Metadata{
			Metadata: &pb.UploadMetadata{
				Key:         key,
				ContentType: contentType,
			},
		},
	}
	if err := stream.Send(metadata); err != nil {
		return err
	}

	// Send data in chunks
	buffer := make([]byte, 1024)
	for {
		n, err := reader.Read(buffer)
		if err == io.EOF {
			break
		}
		if err != nil {
			return err
		}

		chunk := &pb.UploadRequest{
			Data: &pb.UploadRequest_Chunk{
				Chunk: buffer[:n],
			},
		}
		if err := stream.Send(chunk); err != nil {
			return err
		}
	}

	// Close and receive response
	_, err = stream.CloseAndRecv()
	return err
}

// downloadFile downloads a file using streaming
func downloadFile(client pb.FileStorageServiceClient, key string) ([]byte, error) {
	stream, err := client.Download(context.Background(), &pb.DownloadRequest{Key: key})
	if err != nil {
		return nil, err
	}

	var data []byte
	for {
		resp, err := stream.Recv()
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, err
		}

		if chunk := resp.GetChunk(); chunk != nil {
			data = append(data, chunk...)
		}
	}

	return data, nil
}