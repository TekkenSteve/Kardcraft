package service

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"io"
	"strings"
	"time"

	"buf.build/go/protovalidate"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	"file-storage/internal/config"
	"file-storage/internal/middleware"
	"file-storage/internal/policy"
	"file-storage/internal/storage"
	pb "file-storage/pkg/grpc/pb"
)

// FileStorageService implements the gRPC file storage service
type FileStorageService struct {
	pb.UnimplementedFileStorageServiceServer
	factory      *storage.Factory
	middleware   *middleware.Chain
	policyEngine *policy.PolicyEngine
	config       *config.Config
	validator    protovalidate.Validator
}

// NewFileStorageService creates a new file storage service
func NewFileStorageService(factory *storage.Factory, middlewareChain *middleware.Chain, policyEngine *policy.PolicyEngine, cfg *config.Config) *FileStorageService {
	validator, err := protovalidate.New()
	if err != nil {
		panic(fmt.Sprintf("failed to initialize protovalidate validator: %v", err))
	}

	return &FileStorageService{
		factory:      factory,
		middleware:   middlewareChain,
		policyEngine: policyEngine,
		config:       cfg,
		validator:    validator,
	}
}

// === 新增：会话文件管理方法 ===

// UploadConversationFile handles conversation file upload requests
func (s *FileStorageService) UploadConversationFile(stream pb.FileStorageService_UploadConversationFileServer) error {
	// Receive the first message to get metadata
	req, err := stream.Recv()
	if err != nil {
		return status.Errorf(codes.InvalidArgument, "failed to receive upload metadata: %v", err)
	}

	metadata := req.GetMetadata()
	if metadata == nil {
		return status.Errorf(codes.InvalidArgument, "first message must contain metadata")
	}
	if err := s.validateRequest(metadata); err != nil {
		return err
	}

	// Validate required fields
	if metadata.UserId == "" || metadata.SessionId == "" {
		return status.Errorf(codes.InvalidArgument, "user_id and session_id are required")
	}

	// Generate file ID and storage key
	fileId := generateFileId()
	storageKey := fmt.Sprintf("conversations/%s/%s/%s_%s",
		metadata.UserId, metadata.SessionId, fileId, metadata.Filename)

	// Get storage instance
	storageInstance, err := s.getStorage("")
	if err != nil {
		return status.Errorf(codes.Internal, "failed to get storage: %v", err)
	}
	defer storageInstance.Close()

	// Create a pipe for streaming data
	pr, pw := io.Pipe()
	defer pr.Close()

	// Start upload in a goroutine
	uploadDone := make(chan error, 1)
	go func() {
		defer pw.Close()

		fileMetadata := &storage.FileMetadata{
			ContentType:   metadata.ContentType,
			ContentLength: metadata.FileSize,
			CustomMeta: map[string]string{
				"user_id":           metadata.UserId,
				"session_id":        metadata.SessionId,
				"file_id":           fileId,
				"original_filename": metadata.Filename,
			},
		}

		// TODO: Add file validation here
		// if err := s.validateConversationFile(metadata); err != nil {
		//     uploadDone <- err
		//     return
		// }

		err := storageInstance.Upload(stream.Context(), storageKey, pr, fileMetadata)
		uploadDone <- err
	}()

	// Stream data chunks
	var totalSize int64
	for {
		req, err := stream.Recv()
		if err == io.EOF {
			break
		}
		if err != nil {
			pw.CloseWithError(err)
			return status.Errorf(codes.Internal, "failed to receive chunk: %v", err)
		}

		chunk := req.GetChunk()
		if chunk == nil {
			continue
		}

		totalSize += int64(len(chunk))
		if _, err := pw.Write(chunk); err != nil {
			return status.Errorf(codes.Internal, "failed to write chunk: %v", err)
		}
	}

	// Close the writer and wait for upload to complete
	pw.Close()
	if err := <-uploadDone; err != nil {
		return s.handleStorageError(err)
	}

	// Get file metadata for response
	fileMetadata, err := storageInstance.GetMetadata(stream.Context(), storageKey)
	if err != nil {
		return s.handleStorageError(err)
	}

	response := &pb.ConversationFileUploadResponse{
		FileId:     fileId,
		StorageKey: storageKey,
		Size:       totalSize,
		Etag:       fileMetadata.ETag,
		UploadedAt: timestamppb.Now(),
	}

	return stream.SendAndClose(response)
}

// GetConversationFiles gets all files for a conversation
func (s *FileStorageService) GetConversationFiles(ctx context.Context, req *pb.GetConversationFilesRequest) (*pb.GetConversationFilesResponse, error) {
	if err := s.validateRequest(req); err != nil {
		return nil, err
	}

	if req.UserId == "" || req.SessionId == "" {
		return nil, status.Errorf(codes.InvalidArgument, "user_id and session_id are required")
	}

	// Get storage instance
	storageInstance, err := s.getStorage("")
	if err != nil {
		return nil, status.Errorf(codes.Internal, "failed to get storage: %v", err)
	}
	defer storageInstance.Close()

	// List files with session prefix
	prefix := fmt.Sprintf("conversations/%s/%s/", req.UserId, req.SessionId)
	files, err := storageInstance.List(ctx, prefix, 100) // Limit to 100 files per session
	if err != nil {
		return nil, s.handleStorageError(err)
	}

	// Convert to conversation file info
	conversationFiles := make([]*pb.ConversationFileInfo, 0, len(files))
	for _, file := range files {
		fileMetadata, err := storageInstance.GetMetadata(ctx, file.Key)
		if err != nil {
			return nil, s.handleStorageError(err)
		}
		if fileMetadata != nil && fileMetadata.CustomMeta != nil {
			conversationFiles = append(conversationFiles, &pb.ConversationFileInfo{
				FileId:      fileMetadata.CustomMeta["file_id"],
				Filename:    fileMetadata.CustomMeta["original_filename"],
				ContentType: fileMetadata.ContentType,
				FileSize:    fileMetadata.ContentLength,
				StorageKey:  file.Key,
				UploadedAt:  timestamppb.New(file.LastModified),
				CustomMeta:  fileMetadata.CustomMeta,
			})
		}
	}

	return &pb.GetConversationFilesResponse{
		Files: conversationFiles,
	}, nil
}

// DownloadConversationFile downloads a file from a conversation
func (s *FileStorageService) DownloadConversationFile(req *pb.DownloadConversationFileRequest, stream pb.FileStorageService_DownloadConversationFileServer) error {
	if err := s.validateRequest(req); err != nil {
		return err
	}

	if req.FileId == "" {
		return status.Errorf(codes.InvalidArgument, "file_id is required")
	}

	// Get storage instance
	storageInstance, err := s.getStorage("")
	if err != nil {
		return status.Errorf(codes.Internal, "failed to get storage: %v", err)
	}
	defer storageInstance.Close()

	// Find file by file_id across both legacy conversation paths and
	// current presigned-upload paths: <user>/<session>/<file_id>/<filename>.
	prefixes := make([]string, 0, 3)
	if req.UserId != "" {
		prefixes = append(prefixes,
			fmt.Sprintf("conversations/%s/", req.UserId),
			fmt.Sprintf("%s/", req.UserId),
		)
	}
	// Compatibility fallback for historical uploads with mismatched/missing user_id.
	prefixes = append(prefixes, "")

	var targetKey string
	for _, prefix := range prefixes {
		files, err := storageInstance.List(stream.Context(), prefix, 5000)
		if err != nil {
			return s.handleStorageError(err)
		}
		for _, file := range files {
			if file.Metadata != nil && file.Metadata.CustomMeta != nil && file.Metadata.CustomMeta["file_id"] == req.FileId {
				targetKey = file.Key
				break
			}
			if strings.Contains(file.Key, "/"+req.FileId+"/") || strings.Contains(file.Key, req.FileId+"_") {
				targetKey = file.Key
				break
			}
		}
		if targetKey != "" {
			break
		}
	}

	if targetKey == "" {
		return status.Errorf(codes.NotFound, "file not found: %s", req.FileId)
	}

	// Download file
	reader, metadata, err := storageInstance.Download(stream.Context(), targetKey)
	if err != nil {
		return s.handleStorageError(err)
	}
	defer reader.Close()

	metadata = enrichMetadataFromStorageKey(metadata, targetKey, req.FileId)

	// Send metadata first
	metadataMsg := &pb.DownloadResponse{
		Data: &pb.DownloadResponse_Metadata{
			Metadata: &pb.FileMetadata{
				ContentType:   metadata.ContentType,
				ContentLength: metadata.ContentLength,
				Etag:          metadata.ETag,
				LastModified:  timestamppb.New(metadata.LastModified),
				CustomMeta:    metadata.CustomMeta,
			},
		},
	}

	if err := stream.Send(metadataMsg); err != nil {
		return status.Errorf(codes.Internal, "failed to send metadata: %v", err)
	}

	// Stream file data in chunks
	buffer := make([]byte, 32*1024) // 32KB chunks
	for {
		n, err := reader.Read(buffer)
		if err == io.EOF {
			break
		}
		if err != nil {
			return status.Errorf(codes.Internal, "failed to read file: %v", err)
		}

		chunk := &pb.DownloadResponse{
			Data: &pb.DownloadResponse_Chunk{
				Chunk: buffer[:n],
			},
		}

		if err := stream.Send(chunk); err != nil {
			return status.Errorf(codes.Internal, "failed to send chunk: %v", err)
		}
	}

	return nil
}

func enrichMetadataFromStorageKey(
	metadata *storage.FileMetadata,
	storageKey string,
	requestedFileID string,
) *storage.FileMetadata {
	if metadata == nil {
		metadata = &storage.FileMetadata{}
	}
	if metadata.CustomMeta == nil {
		metadata.CustomMeta = make(map[string]string)
	}

	// Pattern A (current HTTP presigned flow):
	//   <user>/<session>/<file_id>/<filename>
	parts := strings.Split(storageKey, "/")
	if len(parts) >= 4 {
		candidateFileID := parts[len(parts)-2]
		candidateFilename := parts[len(parts)-1]
		if strings.HasPrefix(candidateFileID, "file_") && candidateFilename != "" {
			if metadata.CustomMeta["file_id"] == "" {
				metadata.CustomMeta["file_id"] = candidateFileID
			}
			if metadata.CustomMeta["original_filename"] == "" {
				metadata.CustomMeta["original_filename"] = candidateFilename
			}
		}
	}

	// Pattern B (legacy gRPC conversation upload):
	//   conversations/<user>/<session>/<conversation>/<file_id>_<filename>
	if metadata.CustomMeta["original_filename"] == "" {
		last := parts[len(parts)-1]
		if idx := strings.Index(last, "file_"); idx >= 0 {
			rest := last[idx:]
			if sep := strings.Index(rest, "_"); sep >= 0 {
				fileIDAndName := rest
				if secondSep := strings.Index(fileIDAndName[5:], "_"); secondSep >= 0 {
					// Keep legacy behavior conservative: only parse if we can extract a name.
					maybeName := fileIDAndName[5+secondSep+1:]
					if maybeName != "" {
						metadata.CustomMeta["original_filename"] = maybeName
					}
				}
			}
		}
	}

	if metadata.CustomMeta["file_id"] == "" && requestedFileID != "" {
		metadata.CustomMeta["file_id"] = requestedFileID
	}

	return metadata
}

// ValidateFile validates a file (TODO: implement validation logic)
func (s *FileStorageService) ValidateFile(ctx context.Context, req *pb.ValidateFileRequest) (*pb.ValidateFileResponse, error) {
	if err := s.validateRequest(req); err != nil {
		return nil, err
	}

	// TODO: Implement comprehensive file validation
	// For now, basic validation based on file size and type

	var warnings []string
	isValid := true
	validationError := ""

	// Check file size (example: max 100MB)
	maxSize := int64(100 * 1024 * 1024) // 100MB
	if req.FileSize > maxSize {
		isValid = false
		validationError = fmt.Sprintf("file size %d exceeds maximum allowed size %d", req.FileSize, maxSize)
	}

	// Check content type
	allowedTypes := []string{
		"application/pdf",
		"text/plain",
		"application/msword",
		"application/vnd.openxmlformats-officedocument.wordprocessingml.document",
		"text/markdown",
	}

	typeAllowed := false
	for _, allowedType := range allowedTypes {
		if req.ContentType == allowedType {
			typeAllowed = true
			break
		}
	}

	if !typeAllowed {
		isValid = false
		validationError = fmt.Sprintf("content type %s is not allowed", req.ContentType)
	}

	// TODO: Add magic number validation using req.FileHeader
	// TODO: Add virus scanning
	// TODO: Add content analysis

	if req.FileSize > 50*1024*1024 { // Warn for files > 50MB
		warnings = append(warnings, "Large file size may affect processing performance")
	}

	return &pb.ValidateFileResponse{
		IsValid:         isValid,
		ValidationError: validationError,
		Warnings:        warnings,
	}, nil
}

// generateFileId generates a unique file ID
func generateFileId() string {
	bytes := make([]byte, 16)
	rand.Read(bytes)
	return hex.EncodeToString(bytes)
}

// === 原有方法保持不变 ===

// Upload handles file upload requests
func (s *FileStorageService) Upload(stream pb.FileStorageService_UploadServer) error {
	// Receive the first message to get metadata
	req, err := stream.Recv()
	if err != nil {
		return status.Errorf(codes.InvalidArgument, "failed to receive upload metadata: %v", err)
	}

	metadata := req.GetMetadata()
	if metadata == nil {
		return status.Errorf(codes.InvalidArgument, "first message must contain metadata")
	}
	if err := s.validateRequest(metadata); err != nil {
		return err
	}

	// Get storage instance
	storageInstance, err := s.getStorage(metadata.Provider)
	if err != nil {
		return status.Errorf(codes.Internal, "failed to get storage: %v", err)
	}
	defer storageInstance.Close()

	// Create a pipe for streaming data
	pr, pw := io.Pipe()
	defer pr.Close()

	// Start upload in a goroutine
	uploadDone := make(chan error, 1)
	go func() {
		defer pw.Close()

		fileMetadata := &storage.FileMetadata{
			ContentType: metadata.ContentType,
			CustomMeta:  metadata.CustomMeta,
		}

		// Validate upload against policies
		if err := s.policyEngine.ValidateUpload(metadata.Key, fileMetadata); err != nil {
			uploadDone <- err
			return
		}

		err := storageInstance.Upload(stream.Context(), metadata.Key, pr, fileMetadata)
		uploadDone <- err
	}()

	// Stream data chunks
	var totalSize int64
	for {
		req, err := stream.Recv()
		if err == io.EOF {
			break
		}
		if err != nil {
			pw.CloseWithError(err)
			return status.Errorf(codes.Internal, "failed to receive chunk: %v", err)
		}

		chunk := req.GetChunk()
		if chunk == nil {
			continue
		}

		totalSize += int64(len(chunk))
		if _, err := pw.Write(chunk); err != nil {
			return status.Errorf(codes.Internal, "failed to write chunk: %v", err)
		}
	}

	// Close the writer and wait for upload to complete
	pw.Close()
	if err := <-uploadDone; err != nil {
		return s.handleStorageError(err)
	}

	// Get file metadata for response
	fileMetadata, err := storageInstance.GetMetadata(stream.Context(), metadata.Key)
	if err != nil {
		return s.handleStorageError(err)
	}

	response := &pb.UploadResponse{
		Key:        metadata.Key,
		Size:       totalSize,
		Etag:       fileMetadata.ETag,
		UploadedAt: timestamppb.Now(),
	}

	return stream.SendAndClose(response)
}

// Download handles file download requests
func (s *FileStorageService) Download(req *pb.DownloadRequest, stream pb.FileStorageService_DownloadServer) error {
	if err := s.validateRequest(req); err != nil {
		return err
	}

	// Get storage instance
	storageInstance, err := s.getStorage(req.Provider)
	if err != nil {
		return status.Errorf(codes.Internal, "failed to get storage: %v", err)
	}
	defer storageInstance.Close()

	// Download file
	reader, metadata, err := storageInstance.Download(stream.Context(), req.Key)
	if err != nil {
		return s.handleStorageError(err)
	}
	defer reader.Close()

	// Send metadata first
	metadataMsg := &pb.DownloadResponse{
		Data: &pb.DownloadResponse_Metadata{
			Metadata: &pb.FileMetadata{
				ContentType:   metadata.ContentType,
				ContentLength: metadata.ContentLength,
				Etag:          metadata.ETag,
				LastModified:  timestamppb.New(metadata.LastModified),
				CustomMeta:    metadata.CustomMeta,
			},
		},
	}

	if err := stream.Send(metadataMsg); err != nil {
		return status.Errorf(codes.Internal, "failed to send metadata: %v", err)
	}

	// Stream file data in chunks
	buffer := make([]byte, 32*1024) // 32KB chunks
	for {
		n, err := reader.Read(buffer)
		if err == io.EOF {
			break
		}
		if err != nil {
			return status.Errorf(codes.Internal, "failed to read file: %v", err)
		}

		chunk := &pb.DownloadResponse{
			Data: &pb.DownloadResponse_Chunk{
				Chunk: buffer[:n],
			},
		}

		if err := stream.Send(chunk); err != nil {
			return status.Errorf(codes.Internal, "failed to send chunk: %v", err)
		}
	}

	return nil
}

// Delete handles file deletion requests
func (s *FileStorageService) Delete(ctx context.Context, req *pb.DeleteRequest) (*pb.DeleteResponse, error) {
	if err := s.validateRequest(req); err != nil {
		return nil, err
	}

	// Get storage instance
	storageInstance, err := s.getStorage(req.Provider)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "failed to get storage: %v", err)
	}
	defer storageInstance.Close()

	// Delete file
	err = storageInstance.Delete(ctx, req.Key)
	if err != nil {
		return nil, s.handleStorageError(err)
	}

	return &pb.DeleteResponse{Success: true}, nil
}

// Exists handles file existence check requests
func (s *FileStorageService) Exists(ctx context.Context, req *pb.ExistsRequest) (*pb.ExistsResponse, error) {
	if err := s.validateRequest(req); err != nil {
		return nil, err
	}

	// Get storage instance
	storageInstance, err := s.getStorage(req.Provider)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "failed to get storage: %v", err)
	}
	defer storageInstance.Close()

	// Check if file exists
	exists, err := storageInstance.Exists(ctx, req.Key)
	if err != nil {
		return nil, s.handleStorageError(err)
	}

	return &pb.ExistsResponse{Exists: exists}, nil
}

// List handles file listing requests
func (s *FileStorageService) List(ctx context.Context, req *pb.ListRequest) (*pb.ListResponse, error) {
	if err := s.validateRequest(req); err != nil {
		return nil, err
	}

	// Get storage instance
	storageInstance, err := s.getStorage(req.Provider)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "failed to get storage: %v", err)
	}
	defer storageInstance.Close()

	// List files
	files, err := storageInstance.List(ctx, req.Prefix, int(req.Limit))
	if err != nil {
		return nil, s.handleStorageError(err)
	}

	// Convert to protobuf format
	pbFiles := make([]*pb.FileInfo, len(files))
	for i, file := range files {
		pbFiles[i] = &pb.FileInfo{
			Key:          file.Key,
			Size:         file.Size,
			LastModified: timestamppb.New(file.LastModified),
			Etag:         file.ETag,
			ContentType:  file.ContentType,
			Metadata: &pb.FileMetadata{
				ContentType:   file.Metadata.ContentType,
				ContentLength: file.Metadata.ContentLength,
				Etag:          file.Metadata.ETag,
				LastModified:  timestamppb.New(file.Metadata.LastModified),
				CustomMeta:    file.Metadata.CustomMeta,
			},
		}
	}

	return &pb.ListResponse{Files: pbFiles}, nil
}

// GetMetadata handles get metadata requests
func (s *FileStorageService) GetMetadata(ctx context.Context, req *pb.GetMetadataRequest) (*pb.GetMetadataResponse, error) {
	if err := s.validateRequest(req); err != nil {
		return nil, err
	}

	// Get storage instance
	storageInstance, err := s.getStorage(req.Provider)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "failed to get storage: %v", err)
	}
	defer storageInstance.Close()

	// Get metadata
	metadata, err := storageInstance.GetMetadata(ctx, req.Key)
	if err != nil {
		return nil, s.handleStorageError(err)
	}

	return &pb.GetMetadataResponse{
		Metadata: &pb.FileMetadata{
			ContentType:   metadata.ContentType,
			ContentLength: metadata.ContentLength,
			Etag:          metadata.ETag,
			LastModified:  timestamppb.New(metadata.LastModified),
			CustomMeta:    metadata.CustomMeta,
		},
	}, nil
}

// UpdateMetadata handles update metadata requests
func (s *FileStorageService) UpdateMetadata(ctx context.Context, req *pb.UpdateMetadataRequest) (*pb.UpdateMetadataResponse, error) {
	if err := s.validateRequest(req); err != nil {
		return nil, err
	}

	// Get storage instance
	storageInstance, err := s.getStorage(req.Provider)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "failed to get storage: %v", err)
	}
	defer storageInstance.Close()

	// Convert protobuf metadata to internal format
	metadata := &storage.FileMetadata{
		ContentType:   req.Metadata.ContentType,
		ContentLength: req.Metadata.ContentLength,
		ETag:          req.Metadata.Etag,
		LastModified:  req.Metadata.LastModified.AsTime(),
		CustomMeta:    req.Metadata.CustomMeta,
	}

	// Update metadata
	err = storageInstance.UpdateMetadata(ctx, req.Key, metadata)
	if err != nil {
		return nil, s.handleStorageError(err)
	}

	return &pb.UpdateMetadataResponse{Success: true}, nil
}

// GeneratePresignedURL handles presigned URL generation requests
func (s *FileStorageService) GeneratePresignedURL(ctx context.Context, req *pb.GeneratePresignedURLRequest) (*pb.GeneratePresignedURLResponse, error) {
	if err := s.validateRequest(req); err != nil {
		return nil, err
	}

	// Get storage instance
	storageInstance, err := s.getStorage(req.Provider)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "failed to get storage: %v", err)
	}
	defer storageInstance.Close()

	// Convert operation
	var operation storage.Operation
	switch req.Operation {
	case pb.Operation_READ:
		operation = storage.OperationRead
	case pb.Operation_WRITE:
		operation = storage.OperationWrite
	case pb.Operation_DELETE:
		operation = storage.OperationDelete
	default:
		return nil, status.Errorf(codes.InvalidArgument, "invalid operation: %v", req.Operation)
	}

	// Generate presigned URL
	expiry := time.Duration(req.ExpirySeconds) * time.Second
	url, err := storageInstance.GeneratePresignedURL(ctx, req.Key, expiry, operation)
	if err != nil {
		return nil, s.handleStorageError(err)
	}

	return &pb.GeneratePresignedURLResponse{
		Url:       url,
		ExpiresAt: timestamppb.New(time.Now().Add(expiry)),
	}, nil
}

// GetHealth handles health check requests
func (s *FileStorageService) GetHealth(ctx context.Context, req *pb.HealthRequest) (*pb.HealthResponse, error) {
	details := make(map[string]string)
	details["providers"] = fmt.Sprintf("%v", s.factory.ListProviders())
	details["default_provider"] = s.config.Storage.DefaultProvider

	return &pb.HealthResponse{
		Status:    "healthy",
		Timestamp: timestamppb.Now(),
		Details:   details,
	}, nil
}

// getStorage gets a storage instance with middleware applied
func (s *FileStorageService) getStorage(provider string) (storage.Storage, error) {
	storageInstance, err := s.factory.CreateStorage(context.Background(), provider)
	if err != nil {
		return nil, err
	}

	// Apply middleware
	return s.middleware.Apply(storageInstance), nil
}

// handleStorageError converts storage errors to gRPC errors
func (s *FileStorageService) handleStorageError(err error) error {
	if storageErr, ok := err.(*storage.StorageError); ok {
		switch storageErr.Code {
		case storage.ErrorCodeNotFound:
			return status.Error(codes.NotFound, storageErr.Error())
		case storage.ErrorCodeAlreadyExists:
			return status.Error(codes.AlreadyExists, storageErr.Error())
		case storage.ErrorCodePermissionDenied:
			return status.Error(codes.PermissionDenied, storageErr.Error())
		case storage.ErrorCodeInvalidArgument:
			return status.Error(codes.InvalidArgument, storageErr.Error())
		case storage.ErrorCodeUnavailable:
			return status.Error(codes.Unavailable, storageErr.Error())
		case storage.ErrorCodeQuotaExceeded:
			return status.Error(codes.ResourceExhausted, storageErr.Error())
		default:
			return status.Error(codes.Internal, storageErr.Error())
		}
	}
	return status.Error(codes.Internal, err.Error())
}

func (s *FileStorageService) validateRequest(msg proto.Message) error {
	if msg == nil {
		return status.Error(codes.InvalidArgument, "request must not be nil")
	}
	if err := s.validator.Validate(msg); err != nil {
		return status.Errorf(codes.InvalidArgument, "request validation failed: %v", err)
	}
	return nil
}
