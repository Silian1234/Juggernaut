"""Build the exact Unity 2022.3.43f1 uncompressed Mesh fields used by EXO3."""
import struct

import numpy as np

from suit_serial_file import align, array, string


def tangents(positions, normals, uv, triangles):
    a, b, c = triangles.T
    e1, e2 = positions[b] - positions[a], positions[c] - positions[a]
    s1, s2 = uv[b] - uv[a], uv[c] - uv[a]
    determinant = s1[:, 0] * s2[:, 1] - s1[:, 1] * s2[:, 0]
    inverse = np.divide(1, determinant, out=np.zeros_like(determinant),
                        where=np.abs(determinant) > 1e-12)
    triangle_tangent = (e1 * s2[:, 1:2] - e2 * s1[:, 1:2]) * inverse[:, None]
    triangle_bitangent = (e2 * s1[:, 0:1] - e1 * s2[:, 0:1]) * inverse[:, None]
    tangent = np.zeros_like(positions)
    bitangent = np.zeros_like(positions)
    for corner in triangles.T:
        np.add.at(tangent, corner, triangle_tangent)
        np.add.at(bitangent, corner, triangle_bitangent)

    normal_length = np.linalg.norm(normals, axis=1)
    if np.any(normal_length < 1e-7):
        raise ValueError("zero-length vertex normal")
    normal = normals / normal_length[:, None]
    tangent -= normal * np.sum(normal * tangent, axis=1)[:, None]
    length = np.linalg.norm(tangent, axis=1)
    fallback = length < 1e-7
    axis = np.eye(3)[np.argmin(np.abs(normal[fallback]), axis=1)]
    tangent[fallback] = np.cross(axis, normal[fallback])
    tangent /= np.linalg.norm(tangent, axis=1)[:, None]
    sign = np.where(np.sum(np.cross(normal, tangent) * bitangent, axis=1) < 0, -1, 1)
    return np.column_stack((tangent, sign))


def aabb(positions):
    low, high = positions.min(axis=0), positions.max(axis=0)
    return np.concatenate(((low + high) / 2, (high - low) / 2)).astype("<f4").tobytes()


def mesh_updates(lod, bones=None, name="mesh", groups=None):
    positions = np.asarray(lod["v"], dtype="<f4").reshape(-1, 3)
    normals = np.asarray(lod["n"], dtype="<f4").reshape(-1, 3)
    uv = np.asarray(lod["uv"], dtype="<f4").reshape(-1, 2)
    indices = np.asarray(lod["t"], dtype="<u4")
    triangles = indices.reshape(-1, 3)
    count = len(positions)
    if (not count or not len(indices) or len(normals) != count or len(uv) != count
            or int(indices.max()) >= count
            or not all(np.isfinite(data).all() for data in (positions, normals, uv))):
        raise ValueError("invalid mesh positions, normals, UVs or indices")
    if groups is None:
        groups = [len(indices)]
    if sum(groups) != len(indices) or any(size <= 0 or size % 3 for size in groups):
        raise ValueError("expected nonempty triangle groups covering the index buffer")

    submeshes = bytearray()
    first = 0
    for size in groups:
        selected = indices[first:first + size]
        lowest, highest = int(selected.min()), int(selected.max())
        submeshes += struct.pack("<6I", first * 4, size, 0, 0, lowest, highest - lowest + 1)
        submeshes += aabb(positions[selected])
        first += size

    tangent = tangents(positions, normals, uv, triangles)
    channels = np.zeros((14, 4), dtype="u1")
    channels[0] = (0, 0, 0, 3)
    channels[1] = (0, 12, 0, 3)
    channels[2] = (0, 24, 0, 4)
    binds = b""
    bone_aabbs = b""
    if bones:
        channels[4] = (1, 0, 0, 2)
        channels[12] = (2, 0, 0, 4)
        channels[13] = (2, 16, 10, 4)
        matrices = np.array([bone["bindpose"] for bone in bones], dtype="<f4")
        matrices = matrices.reshape(-1, 4, 4).transpose(0, 2, 1)
        weights = np.asarray(lod["bw"], dtype="<f4").reshape(-1, 4)
        joint_indices = np.asarray(lod["bi"], dtype="<u4").reshape(-1, 4)
        if (len(weights) != count or len(joint_indices) != count or np.any(weights < 0)
                or int(joint_indices.max()) >= len(bones)
                or not np.isfinite(matrices).all()
                or not np.allclose(weights.sum(axis=1), 1, atol=1e-5)):
            raise ValueError("invalid skin weights, indices or bind poses")

        local_bounds = []
        for index, matrix in enumerate(matrices):
            vertices = positions[np.any((joint_indices == index) & (weights > 0), axis=1)]
            if len(vertices):
                local = vertices @ matrix[:3, :3].T + matrix[:3, 3]
                local_bounds.append(np.concatenate((local.min(0), local.max(0))))
            else:
                local_bounds.append(np.zeros(6))
        binds = matrices.tobytes()
        bone_aabbs = np.asarray(local_bounds, dtype="<f4").tobytes()

        interleaved = np.empty(count, dtype=np.dtype([("weights", "<f4", 4), ("bones", "<u4", 4)]))
        interleaved["weights"] = weights
        interleaved["bones"] = joint_indices
        vertex_stream = np.column_stack((positions, normals, tangent)).astype("<f4").tobytes()
        vertex_stream += bytes(align(len(vertex_stream), 16) - len(vertex_stream))
        vertex_stream += uv.tobytes()
        vertex_stream += bytes(align(len(vertex_stream), 16) - len(vertex_stream))
        vertex_stream += interleaved.tobytes()
    else:
        channels[4] = (0, 40, 0, 2)
        vertex_stream = np.column_stack((positions, normals, tangent, uv)).astype("<f4").tobytes()

    vertex_data = struct.pack("<II", count, len(channels)) + channels.tobytes()
    vertex_data += array(len(vertex_stream), vertex_stream)
    return {
        "m_Name": string(name),
        "m_SubMeshes": array(len(groups), bytes(submeshes)),
        "m_Shapes": bytes(16),
        "m_BindPose": array(len(bones or []), binds),
        "m_BoneNameHashes": bytes(4),
        "m_RootBoneNameHash": bytes(4),
        "m_BonesAABB": array(len(bones or []), bone_aabbs),
        "m_VariableBoneCountWeights": bytes(4),
        "m_MeshCompression": bytes(1),
        "m_IsReadable": b"\x01",
        "m_KeepVertices": bytes(1),
        "m_KeepIndices": bytes(1),
        "m_IndexFormat": struct.pack("<i", 1),
        "m_IndexBuffer": array(indices.nbytes, indices.tobytes()),
        "m_VertexData": vertex_data,
        "m_CompressedMesh": bytes(164),
        "m_LocalAABB": aabb(positions),
        "m_MeshUsageFlags": struct.pack("<i", int(bool(bones))),
        "m_CookingOptions": struct.pack("<i", 30),
        "m_BakedConvexCollisionMesh": bytes(4),
        "m_BakedTriangleCollisionMesh": bytes(4),
        "m_MeshMetrics[0]": struct.pack("<f", 1),
        "m_MeshMetrics[1]": struct.pack("<f", 1),
        "m_StreamData": bytes(16),
    }

